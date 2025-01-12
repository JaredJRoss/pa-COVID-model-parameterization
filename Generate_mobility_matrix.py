import argparse
import logging

from covid_model_parametrization.utils import utils
from covid_model_parametrization import mobility

utils.config_logger()
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('country_iso3',
                        help='Country ISO3')
    parser.add_argument('-c', '--crossings', action='store_true',
                        help='Read in road border crossings from file. Else download')
    parser.add_argument('-d', '--distances', action='store_true',
                        help='Read in distances between region centroids from file. Else download')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    try:
        mobility.mobility(country_iso3=args.country_iso3.upper(),
                          read_in_crossings=args.crossings,
                          read_in_distances=args.distances)
    except Exception as err:
        logger.error(
            f"Cannot generate mobility matrix, check log for details"
        )
        raise err

