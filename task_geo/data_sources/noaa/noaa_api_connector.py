"""Connector to the NOAA API.


Contributors:

The journal article describing GHCN-Daily is:
Menne, M.J., I. Durre, R.S. Vose, B.E. Gleason, and T.G. Houston, 2012:  An overview
of the Global Historical Climatology Network-Daily Database.  Journal of Atmospheric
and Oceanic Technology, 29, 897-910, doi:10.1175/JTECH-D-11-00103.1.

To acknowledge the specific version of the dataset used, please cite:
Menne, M.J., I. Durre, B. Korzeniewski, S. McNeal, K. Thomas, X. Yin, S. Anthony, R. Ray,
R.S. Vose, B.E.Gleason, and T.G. Houston, 2012: Global Historical Climatology Network -
Daily (GHCN-Daily), Version 3.26
NOAA National Climatic Data Center. http://doi.org/10.7289/V5D21VHZ [2020/03/30].
"""

import logging
import os
from datetime import datetime

import pandas as pd
import requests

from task_geo.data_sources.noaa.ftp_connector import download_noaa_files
from task_geo.data_sources.noaa.references import (
    COUNTRY_AND_TERRITORY_CODES, DATA_DIRECTORY, TERRITORY_ACTIVE_STATIONS_MAP, load_dataset)

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.WARNING)


DEFAULT_METRICS = ['TMAX', 'TMIN', 'TAVG', 'PCRP', 'SNOW', 'SNWD']


def get_stations_by_country(country):
    """Get all stations for a given country code.

    Arguments:
        country(str)

    Returns:
        list[str]
    """

    territory_codes = COUNTRY_AND_TERRITORY_CODES.get(country)
    if territory_codes is None:
        raise ValueError('Wrong country code %s', country)

    stations = list()
    for code in territory_codes:
        code_stations = TERRITORY_ACTIVE_STATIONS_MAP.get(code)
        if code_stations is not None:
            stations.extend(code_stations)

    return stations


def get_request_urls(country, start_date, end_date=None, metrics=None):
    """Encodes the parameters the URL to make a GET request

    Arguments:
        country(str): FIPS Country code
        start_date(datetime)
        end_date(datetime): Defaults to today
        metrics(list[str]): Optional.List of metrics to retrieve,valid values are:
            TMIN: Minimum temperature.
            TMAX: Maximum temperature.
            TAVG: Average of temperature.
            SNOW: Snowfall (mm).
            SNWD: Snow depth (mm).
            PRCP: Precipitation.

    Returns:
        str
    """

    base_url = 'https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries'
    max_stations_req = 50

    if metrics is None:
        metrics = DEFAULT_METRICS

    request_common_args = (
        f'&format=json'
        f'&units=metric'
        f'&dataTypes={",".join(metrics)}'
    )

    if end_date is None:
        end_date = datetime.now()

    start = start_date.date().isoformat()
    end = end_date.date().isoformat()

    stations_list = get_stations_by_country(country)
    if len(stations_list) < max_stations_req:
        stations = ','.join(stations_list)
        return [
            f'{base_url}&stations={stations}&startDate={start}&endDate={end}{request_common_args}']

    else:
        chunked_station_list = [
            stations_list[i:i + max_stations_req]
            for i in range(0, len(stations_list), max_stations_req)
        ]

        return [
            (
                f'{base_url}&stations={",".join(chunk)}&startDate={start}'
                f'&endDate={end}{request_common_args}'
            )
            for chunk in chunked_station_list
        ]


def get_parse_response(urls):
    """Calls the urls in urls, return responses and errors

    Arguments:
        urls(list[str]): Urls as generated by `get_request_urls`.

    Returns:
        tuple[list[dict], list[Exception]]:
            The first element of the tuple is a list of dictionary with all the responses.
            The second element is a list with all the exceptions raised during the calls.
    """

    results = list()
    errors = list()

    total = len(urls) - 1
    for i, url in enumerate(urls):
        logging.debug('Making request %s / %s', i + 1, total + 1)
        response = requests.get(url)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            errors.append({
                'url': url,
                'error': response.json(),
            })
            continue

        results.extend(response.json())

    return results, errors


def noaa_api_connector(countries, start_date, end_date=None, metrics=None):
    """Get data from NOAA API.

    Arguments:
        countries(list[str]): List of FIPS country codes to retrieve.
        start_date(datetime)
        end_date(datetime)
        metrics(list[str]): Optional.List of metrics to retrieve,valid values are:
            TMIN: Minimum temperature.
            TMAX: Maximum temperature.
            TAVG: Average of temperature.
            SNOW: Snowfall (mm).
            SNWD: Snow depth (mm).

    Returns:
        tuple[list[dict], list[Exception]]
    """
    if not os.path.isfile(f'{DATA_DIRECTORY}/stations_metadata.txt'):
        download_noaa_files(large_files=False)

    result = list()
    for country in countries:
        logging.info('Requesting data for %s', country)
        urls = get_request_urls(country, start_date, end_date, metrics)
        country_results, errors = get_parse_response(urls)

        if errors:
            logging.info('The following errors where found during the operation:')
            for error in errors:
                logging.info(error)

        result.extend(country_results)

    data = pd.DataFrame(result)
    stations = load_dataset('stations')
    data = data.merge(stations, how='left', left_on='STATION', right_on='ID')

    del data['ID']
    del data['STATE']

    columns = [
        'DATE', 'STATION', 'LATITUDE', 'LONGITUDE', 'ELEVATION', 'NAME',
        'GSN FLAG', 'HCN/CRN FLAG', 'WMO ID'
    ]

    if metrics is None:
        metrics = DEFAULT_METRICS

    columns.extend([metric for metric in metrics if metric in data.columns])
    return data[columns]
