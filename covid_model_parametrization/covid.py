# script that pulls data from several sources and generate COVID-19 breakdown for subnational SEIR model

import datetime
import os
import logging
import itertools
import getpass
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

from covid_model_parametrization.utils import utils
from covid_model_parametrization.config import Config
from covid_model_parametrization.utils.who import get_WHO_data


logger = logging.getLogger(__name__)


def covid(country_iso3, download_covid=False, config=None):
    # Get config file
    if config is None:
        config = Config()
    parameters = config.parameters(country_iso3)

    # Get input covid file
    input_dir = os.path.join(config.DIR_PATH, config.INPUT_DIR, country_iso3)

    # Download latest covid file tiles and read them in
    if download_covid:
        get_covid_data(parameters["covid"], country_iso3, input_dir, config)
    df_covid = pd.read_csv(
        "{}/{}".format(
            os.path.join(input_dir, config.COVID_OUTPUT_DIR),
            parameters["covid"]["filename"],
        ),
        header=parameters["covid"]["header"],
        skiprows=parameters["covid"]["skiprows"],
    )
    # drop duplicates. Some datasets have duplicated rows on HDX
    df_covid=df_covid.drop_duplicates()

    # convert to standard HLX
    if "hlx_dict" in parameters["covid"]:
        df_covid = df_covid.rename(columns=parameters["covid"]["hlx_dict"])

    # in South Sudan we have individual case data which need to be aggregated at the ADM2 level 
    if (
        parameters["covid"]["individual_case_data"]
        and parameters["covid"]["admin_level"] == 2
    ):
        df_covid = pd.pivot_table(
            df_covid,
            index=[
                config.HLX_TAG_DATE,
                config.HLX_TAG_ADM1_NAME,
                config.HLX_TAG_ADM2_NAME,
            ],
            aggfunc="count",
        ).reset_index()
        df_covid = df_covid.rename(columns={"Case No.": config.HLX_TAG_TOTAL_CASES})
        df_covid = df_covid[
            [
                config.HLX_TAG_DATE,
                config.HLX_TAG_ADM1_NAME,
                config.HLX_TAG_ADM2_NAME,
                config.HLX_TAG_TOTAL_CASES,
            ]
        ]
    
    # convert to numeric
    if parameters["covid"]["cases"]:
        df_covid[config.HLX_TAG_TOTAL_CASES] = convert_to_numeric(
            df_covid[config.HLX_TAG_TOTAL_CASES]
        )
    if parameters["covid"]["deaths"]:
        df_covid[config.HLX_TAG_TOTAL_DEATHS] = convert_to_numeric(
            df_covid[config.HLX_TAG_TOTAL_DEATHS]
        )
    df_covid.fillna(0, inplace=True)

    # remove Total for spatially disaggregated data
    df_covid = df_covid[df_covid[config.HLX_TAG_ADM1_NAME] != "Total"]
    # cleaning up names before using the replace dictionary
    df_covid[config.HLX_TAG_ADM1_NAME] = df_covid[config.HLX_TAG_ADM1_NAME].str.replace(
        "Province", ""
    )
    df_covid[config.HLX_TAG_ADM1_NAME] = df_covid[config.HLX_TAG_ADM1_NAME].str.replace(
        "State", ""
    )
    df_covid[config.HLX_TAG_ADM1_NAME] = df_covid[config.HLX_TAG_ADM1_NAME].str.strip()
    # apply replace dict to match ADM unit names in the COD with teh COVID data
    if (
        "replace_dict" in parameters["covid"]
        and parameters["covid"]["admin_level"] == 1
    ):
        df_covid[config.HLX_TAG_ADM1_NAME] = df_covid[config.HLX_TAG_ADM1_NAME].replace(
            parameters["covid"]["replace_dict"]
        )
        # Some datasets have mutliple rows corresponsing to the same ADM1
        df_covid=df_covid.groupby([config.HLX_TAG_ADM1_NAME,config.HLX_TAG_DATE]).sum().reset_index()
    if (
        "replace_dict" in parameters["covid"]
        and parameters["covid"]["admin_level"] == 2
    ):
        df_covid[config.HLX_TAG_ADM2_NAME] = df_covid[config.HLX_TAG_ADM2_NAME].replace(
            parameters["covid"]["replace_dict"]
        )
        # Some datasets have mutliple rows corresponsing to the same ADM2
        df_covid=df_covid.groupby([config.HLX_TAG_ADM2_NAME,config.HLX_TAG_DATE]).sum().reset_index()

    # Get exposure file
    try:
        exposure_file = f"{config.SADD_output_dir().format(country_iso3)}/{config.EXPOSURE_GEOJSON.format(country_iso3)}"
        exposure_gdf = gpd.read_file(exposure_file)
    except Exception as err:
        logger.error(
            f"Cannot get exposure file for {country_iso3}, COVID file not generate"
        )
        raise err

    output_fields = [
        config.HLX_TAG_ADM1_PCODE,
        config.HLX_TAG_ADM2_PCODE,
        config.HLX_TAG_DATE,
        config.HLX_TAG_TOTAL_CASES,
        config.HLX_TAG_TOTAL_DEATHS,
    ]
    output_df_covid = pd.DataFrame(columns=output_fields)

    ADM2_ADM1_pcodes = get_dict_pcodes(exposure_gdf, "ADM2_PCODE")

    ADM0_CFR=0
    if not parameters["covid"]["deaths"]:
        # missing death data, getting it from WHO at the national level
        who_df = get_WHO_data(config, country_iso3,hxlize=False,\
            smooth_data=parameters['WHO']['smooth_data'],n_days_smoothing=parameters['WHO']['n_days_smoothing'])
        who_df['Date_reported']=pd.to_datetime(who_df['Date_reported'])
        who_df=who_df.sort_values(by='Date_reported')
        who_df=who_df.set_index('Date_reported')
        latest_date=who_df.tail(1).index.values[0]
        # get the CFR from the latest month, to account for recent reporting rate estimation
        who_df=who_df.loc[latest_date-np.timedelta64(30,'D'):latest_date]
        deaths=who_df.iloc[-1]['Cumulative_deaths']-who_df.iloc[0]['Cumulative_deaths']
        cases=who_df.iloc[-1]['Cumulative_cases']-who_df.iloc[0]['Cumulative_cases']
        ADM0_CFR=deaths/cases
        if deaths<100 or ADM0_CFR> 0.3:
            # if it's less than 100 use the cumulative to reduce noise
            # When there are adjustments to the data we may have a jump in the CFR
            # calcualted from the latest month,i t should be captured by the ADM0_CFR> 0.3 
            deaths=who_df.iloc[-1]['Cumulative_deaths']
            cases=who_df.iloc[-1]['Cumulative_cases']
            ADM0_CFR=deaths/cases

    if parameters["covid"]["admin_level"] == 2:
        ADM2_names = get_dict_pcodes(
            exposure_gdf, parameters["covid"]["adm2_name_exp"], "ADM2_PCODE"
        )
        df_covid[config.HLX_TAG_ADM2_PCODE] = df_covid[config.HLX_TAG_ADM2_NAME].map(
            ADM2_names
        )
        if df_covid[config.HLX_TAG_ADM2_PCODE].isnull().sum() > 0:
            logger.warning(
                "missing PCODE for the following admin units "
            )
            logger.warning(
                df_covid[df_covid[config.HLX_TAG_ADM2_PCODE].isnull()][config.HLX_TAG_ADM2_NAME].values
            )
            # print(df_covid)
            return
        df_covid[config.HLX_TAG_ADM1_PCODE] = df_covid[config.HLX_TAG_ADM2_PCODE].map(
            ADM2_ADM1_pcodes
        )
        adm1pcode = df_covid[config.HLX_TAG_ADM1_PCODE]
        adm2pcodes = df_covid[config.HLX_TAG_ADM2_PCODE]
        date = pd.to_datetime(
            df_covid[config.HLX_TAG_DATE], format=parameters["covid"]["date_format"]
        )
        date = date.dt.strftime("%Y-%m-%d")
        adm2cases = (
            df_covid[config.HLX_TAG_TOTAL_CASES]
            if parameters["covid"]["cases"]
            else None
        )
        adm2deaths = (
            df_covid[config.HLX_TAG_TOTAL_DEATHS]
            if parameters["covid"]["deaths"]
            else None
        )
        if not parameters["covid"]["deaths"]:
            adm2deaths=[cases*ADM0_CFR for cases in adm2cases]
        
        raw_data = {
            config.HLX_TAG_ADM1_PCODE: adm1pcode,
            config.HLX_TAG_ADM2_PCODE: adm2pcodes,
            config.HLX_TAG_DATE: date,
            config.HLX_TAG_TOTAL_CASES: adm2cases,
            config.HLX_TAG_TOTAL_DEATHS: adm2deaths,
        }
        output_df_covid = output_df_covid.append(
            pd.DataFrame(raw_data), ignore_index=True
        )
    elif parameters["covid"]["admin_level"] == 1:
        if parameters["covid"].get("federal_state_dict", False):
            # for Somalia we replace the ADM1_PCODE the name of the ADM1 and with the name of the state
            # this is done according to the dictionary
            exposure_gdf["ADM1_PCODE"] = exposure_gdf[
                parameters["covid"]["adm1_name_exp"]
            ].replace(parameters["covid"]["federal_state_dict"])
            exposure_gdf[parameters["covid"]["adm1_name_exp"]] = exposure_gdf[
                "ADM1_PCODE"
            ]
        # get dictionary of ADM1 pcodes
        ADM1_names = get_dict_pcodes(
            exposure_gdf, parameters["covid"]["adm1_name_exp"], "ADM1_PCODE"
        )
        # create new column with pcodes
        df_covid[config.HLX_TAG_ADM1_PCODE] = df_covid[config.HLX_TAG_ADM1_NAME].map(
            ADM1_names
        )
        # check if any pcode is missing
        if df_covid[config.HLX_TAG_ADM1_PCODE].isnull().sum() > 0:
            logger.warning("missing PCODE for the following admin units :")
            logger.warning(
                df_covid[df_covid[config.HLX_TAG_ADM1_PCODE].isnull()][config.HLX_TAG_ADM1_NAME].values
            )
        # get the full list of gender/age combinations to calculate the sum of population in adm2_pop_fractions
        # in principle we could use the sum in the exposure but it's safer to recalculate it
        gender_age_groups = list(
            itertools.product(config.GENDER_CLASSES, config.AGE_CLASSES)
        )
        gender_age_group_names = [
            "{}_{}".format(gender_age_group[0], gender_age_group[1])
            for gender_age_group in gender_age_groups
        ]
            
        for _, row in df_covid.iterrows():
            adm2_pop_fractions = get_adm2_to_adm1_pop_frac(
                row[config.HLX_TAG_ADM1_PCODE], exposure_gdf, gender_age_group_names
            )
            adm1pcode = row[config.HLX_TAG_ADM1_PCODE]
            date = datetime.datetime.strptime(
                row[config.HLX_TAG_DATE], parameters["covid"]["date_format"]
            ).strftime("%Y-%m-%d")
            adm2cases = scale_adm1_by_adm2_pop(
                parameters["covid"]["cases"],
                config.HLX_TAG_TOTAL_CASES,
                row,
                adm2_pop_fractions,
            )
            adm2deaths = scale_adm1_by_adm2_pop(
                parameters["covid"]["deaths"],
                config.HLX_TAG_TOTAL_DEATHS,
                row,
                adm2_pop_fractions,
            )
            if not parameters["covid"]["deaths"]:
                adm2deaths=[cases*ADM0_CFR for cases in adm2cases]
               
            adm2pcodes = [v for v in adm2_pop_fractions.keys()]
            raw_data = {
                config.HLX_TAG_ADM1_PCODE: adm1pcode,
                config.HLX_TAG_ADM2_PCODE: adm2pcodes,
                config.HLX_TAG_DATE: date,
                config.HLX_TAG_TOTAL_CASES: adm2cases,
                config.HLX_TAG_TOTAL_DEATHS: adm2deaths,
            }
            output_df_covid = output_df_covid.append(
                pd.DataFrame(raw_data), ignore_index=True
            )
    else:
        logger.error(f"Missing admin_level info for COVID data")
    # cross-check: the total must match
    if (
        abs(
            (
                output_df_covid[config.HLX_TAG_TOTAL_CASES].sum()
                - df_covid[config.HLX_TAG_TOTAL_CASES].sum()
            )
        )
        > 10
    ):
        logger.warning("The sum of input and output files don't match")

    if not parameters["covid"]["cumulative"]:
        logger.info(f"Calculating cumulative numbers COVID data")
        groups = [
            config.HLX_TAG_ADM1_PCODE,
            config.HLX_TAG_ADM2_PCODE,
            config.HLX_TAG_DATE,
        ]
        # TODO check this was not numeric in the case of SSD
        output_df_covid[config.HLX_TAG_TOTAL_CASES]=pd.to_numeric(output_df_covid[config.HLX_TAG_TOTAL_CASES])
        output_df_covid[config.HLX_TAG_TOTAL_DEATHS]=pd.to_numeric(output_df_covid[config.HLX_TAG_TOTAL_DEATHS])
        # get sum by day (in case multiple reports per day)
        output_df_covid = (
            output_df_covid.groupby(groups).sum().sort_values(by=config.HLX_TAG_DATE)
        )
        # get cumsum by day (grouped by ADM2)
        output_df_covid = (
            output_df_covid.groupby(config.HLX_TAG_ADM2_PCODE).cumsum().reset_index()
        )

    if parameters["covid"].get("federal_state_dict", False):
        # bring back the adm1 pcode that we modified to calculate the sum
        output_df_covid[config.HLX_TAG_ADM1_PCODE] = output_df_covid[
            config.HLX_TAG_ADM2_PCODE
        ].map(ADM2_ADM1_pcodes)

    # Write to file
    output_df_covid["created_at"] = str(datetime.datetime.now())
    output_df_covid["created_by"] = getpass.getuser()
    output_csv = get_output_filename(country_iso3, config)
    logger.info(f"Writing to file {output_csv}")
    output_df_covid.to_csv(output_csv, index=False)


def get_dict_pcodes(exposure, adm_unit_name, adm_unit_pcode="ADM1_PCODE"):
    pcode_dict = dict()
    for k, v in exposure.groupby(adm_unit_name):
        pcode_dict[k] = v.iloc[0, :][adm_unit_pcode]
    return pcode_dict


def scale_adm1_by_adm2_pop(parameters_val, tag, df_row, fractions):
    if parameters_val:
        adm1val = df_row[tag]
        adm2val = [v * adm1val for v in fractions.values()]
    else:
        adm2val = None
    return adm2val


def convert_to_numeric(df_col):
    # TODO check conversions
    if df_col.dtype == "object":
        df_col = df_col.str.replace(",", "")
        df_col = df_col.str.replace("-", "")
        df_col = pd.to_numeric(df_col, errors="coerce")
    return df_col


def get_output_filename(country_iso3, config):
    # get the filename for writing the file
    output_dir = config.COVID_output_dir().format(country_iso3)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return os.path.join(output_dir, config.COVID_OUTPUT_CSV.format(country_iso3))


def get_adm2_to_adm1_pop_frac(pcode, exposure_gdf, gender_age_group_names):
    # get the full exposure and returns a dictionary with
    # the fraction of the population of each ADM2
    exp_adm1 = exposure_gdf[exposure_gdf["ADM1_PCODE"] == pcode]
    adm2_pop = exp_adm1[gender_age_group_names].sum(axis=1)
    adm2_pop_fractions = dict(zip(exp_adm1["ADM2_PCODE"], adm2_pop / adm2_pop.sum()))
    return adm2_pop_fractions


def get_covid_data(parameters, country_iso3, input_dir, config):
    # download covid data from HDX
    if parameters["url"] == 'None':
        logger.info(f"URL missing for {country_iso3}")
        return False
    logger.info(f"Getting COVID data for {country_iso3}")
    download_dir = os.path.join(input_dir, config.COVID_OUTPUT_DIR)
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    covid_filename = os.path.join(download_dir, parameters["filename"])
    try:
        utils.download_url(parameters["url"], covid_filename)
    except Exception:
        logger.warning(f"Cannot download COVID file from for {country_iso3}")
