# COVID model parameterization

[Input description (Google slides)](https://docs.google.com/presentation/d/16hplfTHyJtXoAXTLgNp3LHWP2Upig0eofGcufOsv3RY/edit?usp=sharing)

[Status tracking sheet (Google sheets)](https://docs.google.com/spreadsheets/d/1F-15iyDf_v7hBtr-jdCQMptt5bSFY52YivYRyLFVFBQ/edit?usp=sharing)

[Latest input file (zip)](https://drive.google.com/file/d/1gK3opqhwCc4BRu5PvnYagi0sSI6qnyxn/view)


## Exposure

### Setup

Download the country boundaries shapefile from HDX and place in `Inputs/$COUNTRY_ISO3/Shapefile/`. Unzip the contents
and record the directory and shapefile names in the config file.  Commit the shapefile to the repository.

### Running
To run, execute:
```bash
python Generate_SADD_exposure_from_tiff.py -d
```
The `-d ` flag is for downloading the WolrdPop file the first time you run.  

## Vulnerability

### Setup

Perform the same setup with boundaries shapefile as for the exposure. 

Download food security data from [IPC](http://www.ipcinfo.org/ipc-country-analysis/population-tracking-tool/en/).
Select the country and only data from 2020, save the excel file to 'Inputs/$COUNTRY_ISO3/IPC'. 
Add the filename to the config file, and commit the excel file to the repository. 
. 
## Running 

To run, execute:
```bash
python Generate_vulnerability_file.py -d
```
The `-d ` flag is for downloading and mosaicing the GHS data the first time you run.

### Methodology

Urban / rural data is taken from [GHS](https://ghsl.jrc.ec.europa.eu/). We use the GHS-SMOD raster at 1 km resolution
to determine which cells within a province are urban vs rural. The description of the 
classifcations can be found [here](https://ghsl.jrc.ec.europa.eu/documents/GHSL_Data_Package_2019.pdf).
We take anything denser than suburban (class 21 or above) to be urban, and the rest to be rural.
For more information about the definition of urban vs rural settlements, see 
[here](https://ghsl.jrc.ec.europa.eu/degurbaDefinitions.php).

Then we use the GHS-POP raster to calculate the number of people per urban or rural cell,
and compute the fraction of the population residing in urban cells. 

