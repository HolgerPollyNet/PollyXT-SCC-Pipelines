"""
Routines for converting PollyXT files to SCC files
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple
from enum import Enum, IntEnum

from netCDF4 import Dataset
import numpy as np

from pollyxt_pipelines.polly_to_scc import pollyxt
from pollyxt_pipelines.locations import Location
from pollyxt_pipelines import utils
from pollyxt_pipelines.polly_to_scc.exceptions import (
    NoMeasurementsInTimePeriod,
    TimeOutsideFile,
)


class Wavelength(Enum):
    """Laser wavelength"""

    NM_355 = 355
    NM_532 = 532


class Atmosphere(IntEnum):
    """
    Which atmosphere to use to processing. These are the possible values for `molecular_calc`.
    """

    AUTOMATIC = 0
    RADIOSONDE = 1
    CLOUDNET = 2
    STANDARD_ATMOSPHERE = 4

    @staticmethod
    def from_string(x: str):
        x = x.lower().strip()
        if x == "automatic":
            return Atmosphere.AUTOMATIC
        if x == "radiosonde":
            return Atmosphere.RADIOSONDE
        if x == "cloudnet":
            return Atmosphere.CLOUDNET
        if x == "standard":
            return Atmosphere.STANDARD_ATMOSPHERE

        raise ValueError(f"Unknown atmosphere {x}")


def create_scc_netcdf(
    pf: pollyxt.PollyXTFile,
    output_path: Path,
    location: Location,
    atmosphere=Atmosphere.STANDARD_ATMOSPHERE,
) -> Tuple[str, Path]:
    """
    Convert a PollyXT netCDF file to a SCC file.

    Parameters:
        pf: An opened PollyXT file. When you create this, you can specify the time period of interest.
        output_path: Where to store the produced netCDF file
        location: Where did this measurement take place
        atmosphere: What kind of atmosphere to use.

    Note:
        If atmosphere is set to Atmosphere.SOUNDING, the `Sounding_File_Name` attribute will be set to
        `rs_{MEASUREMENT_ID}.rs`, ie the filename of the accompaning radiosonde. This file is *not* created
        by this function.

    Returns:
        A tuple containing  the measurement ID and the output path
    """

    # Calculate measurement ID
    measurement_id = pf.start_date.strftime(f"%Y%m%d{location.scc_code}%H%M")

    # Create SCC file
    # Output filename is always the measurement ID
    output_filename = output_path / f"{measurement_id}.nc"
    nc = Dataset(output_filename, "w")

    # Create dimensions (mandatory!)
    nc.createDimension("points", np.size(pf.raw_signal, axis=1))
    nc.createDimension("channels", np.size(pf.raw_signal, axis=2))
    nc.createDimension("time", None)
    nc.createDimension("nb_of_time_scales", 1)
    nc.createDimension("scan_angles", 1)

    # Create Global Attributes (mandatory!)
    nc.Measurement_ID = measurement_id
    nc.RawData_Start_Date = pf.start_date.strftime("%Y%m%d")
    nc.RawData_Start_Time_UT = pf.start_date.strftime("%H%M%S")
    nc.RawData_Stop_Time_UT = pf.end_date.strftime("%H%M%S")

    # Create Global Attributes (optional)
    nc.RawBck_Start_Date = nc.RawData_Start_Date
    nc.RawBck_Start_Time_UT = nc.RawData_Start_Time_UT
    nc.RawBck_Stop_Time_UT = nc.RawData_Stop_Time_UT
    if atmosphere == Atmosphere.RADIOSONDE:
        nc.Sounding_File_Name = f"rs_{measurement_id[:-2]}.nc"
    # nc.Overlap_File_Name = 'ov_' + selected_start.strftime('%Y%m%daky%H') + '.nc'

    # Custom attribute for configuration ID
    # From 04:00 until 16:00 we use daytime configuration
    if pf.start_date.replace(
        hour=4, minute=0
    ) < pf.start_date and pf.start_date < pf.start_date.replace(hour=16, minute=0):
        nc.X_PollyXTPipelines_Configuration_ID = location.daytime_configuration
    else:
        nc.X_PollyXTPipelines_Configuration_ID = location.nighttime_configuration

    # Create Variables. (mandatory)
    raw_data_start_time = nc.createVariable(
        "Raw_Data_Start_Time", "i4", dimensions=("time", "nb_of_time_scales"), zlib=True
    )
    raw_data_stop_time = nc.createVariable(
        "Raw_Data_Stop_Time", "i4", dimensions=("time", "nb_of_time_scales"), zlib=True
    )
    raw_lidar_data = nc.createVariable(
        "Raw_Lidar_Data", "f8", dimensions=("time", "channels", "points"), zlib=True
    )
    channel_id = nc.createVariable(
        "channel_ID", "i4", dimensions=("channels"), zlib=True
    )
    id_timescale = nc.createVariable(
        "id_timescale", "i4", dimensions=("channels"), zlib=True
    )
    laser_pointing_angle = nc.createVariable(
        "Laser_Pointing_Angle", "f8", dimensions=("scan_angles"), zlib=True
    )
    laser_pointing_angle_of_profiles = nc.createVariable(
        "Laser_Pointing_Angle_of_Profiles",
        "i4",
        dimensions=("time", "nb_of_time_scales"),
        zlib=True,
    )
    laser_shots = nc.createVariable(
        "Laser_Shots", "i4", dimensions=("time", "channels"), zlib=True
    )
    background_low = nc.createVariable(
        "Background_Low", "f8", dimensions=("channels"), zlib=True
    )
    background_high = nc.createVariable(
        "Background_High", "f8", dimensions=("channels"), zlib=True
    )
    molecular_calc = nc.createVariable("Molecular_Calc", "i4", dimensions=(), zlib=True)
    nc.createVariable("Pol_Calib_Range_Min", "f8", dimensions=("channels"), zlib=True)
    nc.createVariable("Pol_Calib_Range_Max", "f8", dimensions=("channels"), zlib=True)
    pressure_at_lidar_station = nc.createVariable(
        "Pressure_at_Lidar_Station", "f8", dimensions=(), zlib=True
    )
    temperature_at_lidar_station = nc.createVariable(
        "Temperature_at_Lidar_Station", "f8", dimensions=(), zlib=True
    )
    lr_input = nc.createVariable("LR_Input", "i4", dimensions=("channels"), zlib=True)

    # Fill Variables with Data. (mandatory)
    raw_data_start_time[:] = (
        pf.measurement_time[~pf.calibration_mask, 1] - pf.measurement_time[0, 1]
    )
    raw_data_stop_time[:] = (
        pf.measurement_time[~pf.calibration_mask, 1] - pf.measurement_time[0, 1]
    ) + 30
    raw_lidar_data[:] = pf.raw_signal_swap[~pf.calibration_mask]
    channel_id[:] = np.array(location.channel_id)
    id_timescale[:] = np.zeros(np.size(pf.raw_signal[~pf.calibration_mask], axis=2))
    laser_pointing_angle[:] = int(pf.zenith_angle.item(0))
    laser_pointing_angle_of_profiles[:] = np.zeros(
        np.size(pf.raw_signal[~pf.calibration_mask], axis=0)
    )
    laser_shots[:] = pf.measurement_shots[~pf.calibration_mask]
    background_low[:] = np.array(location.background_low)
    background_high[:] = np.array(location.background_high)
    molecular_calc[:] = int(atmosphere)
    pressure_at_lidar_station[:] = location.pressure
    temperature_at_lidar_station[:] = location.temperature
    lr_input[:] = np.array(location.lr_input)

    # Close the netCDF file.
    nc.close()

    return measurement_id, output_filename


def create_scc_calibration_netcdf(
    pf: pollyxt.PollyXTFile,
    output_path: Path,
    location: Location,
    wavelength: Wavelength,
    pol_calib_range_min: int = 1200,
    pol_calib_range_max: int = 2500,
) -> Tuple[str, Path]:
    """
    From a PollyXT netCDF file, create the corresponding calibration SCC file.
    Calibration times are:
    - 02:31 to 02:41
    - 17:31 to 17:41
    - 21:31 to 21:41
    Take care to create the `PollyXTFile` with these intervals.

    Parameters:
        pf: An opened PollyXT file
        output_path: Where to store the produced netCDF file
        location: Where did this measurement take place
        wavelength: Calibration for 355nm or 532nm
        pol_calib_range_min: Calibration contant calculation, minimum height
        pol_calib_range_max: Calibration contant calculation, maximum height

    Returns:
        A tuple containing the measurement ID and the output path
    """

    # Calculate measurement ID
    measurement_id = pf.start_date.strftime(f"%Y%m%d{location.scc_code}%H")

    # Create SCC file
    # Output filename is always the measurement ID
    if wavelength == Wavelength.NM_355:
        output_filename = output_path / f"calibration_{measurement_id}_355.nc"
    elif wavelength == Wavelength.NM_532:
        output_filename = output_path / f"calibration_{measurement_id}_532.nc"
    else:
        raise ValueError(f"Unknown wavelength {wavelength}")
    nc = Dataset(output_filename, "w")

    # Create Dimensions. (mandatory)
    nc.createDimension("points", np.size(pf.raw_signal, axis=1))
    nc.createDimension("channels", 4)
    nc.createDimension("time", 3)
    nc.createDimension("nb_of_time_scales", 1)
    nc.createDimension("scan_angles", 1)

    # Create Global Attributes. (mandatory)
    nc.RawData_Start_Date = pf.start_date.strftime("%Y%m%d")
    nc.RawData_Start_Time_UT = pf.start_date.strftime("%H%M%S")
    nc.RawData_Stop_Time_UT = pf.end_date.strftime("%H%M%S")

    # Create Global Attributes (optional)
    nc.RawBck_Start_Date = nc.RawData_Start_Date
    nc.RawBck_Start_Time_UT = nc.RawData_Start_Time_UT
    nc.RawBck_Stop_Time_UT = nc.RawData_Stop_Time_UT

    # Create Variables. (mandatory)
    raw_data_start_time = nc.createVariable(
        "Raw_Data_Start_Time", "i4", dimensions=("time", "nb_of_time_scales"), zlib=True
    )
    raw_data_stop_time = nc.createVariable(
        "Raw_Data_Stop_Time", "i4", dimensions=("time", "nb_of_time_scales"), zlib=True
    )
    raw_lidar_data = nc.createVariable(
        "Raw_Lidar_Data", "f8", dimensions=("time", "channels", "points"), zlib=True
    )
    channel_id = nc.createVariable(
        "channel_ID", "i4", dimensions=("channels"), zlib=True
    )
    id_timescale = nc.createVariable(
        "id_timescale", "i4", dimensions=("channels"), zlib=True
    )
    laser_pointing_angle = nc.createVariable(
        "Laser_Pointing_Angle", "f8", dimensions=("scan_angles"), zlib=True
    )
    laser_pointing_angle_of_profiles = nc.createVariable(
        "Laser_Pointing_Angle_of_Profiles",
        "i4",
        dimensions=("time", "nb_of_time_scales"),
        zlib=True,
    )
    laser_shots = nc.createVariable(
        "Laser_Shots", "i4", dimensions=("time", "channels"), zlib=True
    )
    background_low = nc.createVariable(
        "Background_Low", "f8", dimensions=("channels"), zlib=True
    )
    background_high = nc.createVariable(
        "Background_High", "f8", dimensions=("channels"), zlib=True
    )
    molecular_calc = nc.createVariable("Molecular_Calc", "i4", dimensions=(), zlib=True)
    pol_calib_range_min_var = nc.createVariable(
        "Pol_Calib_Range_Min", "f8", dimensions=("channels"), zlib=True
    )
    pol_calib_range_max_var = nc.createVariable(
        "Pol_Calib_Range_Max", "f8", dimensions=("channels"), zlib=True
    )
    pressure_at_lidar_station = nc.createVariable(
        "Pressure_at_Lidar_Station", "f8", dimensions=(), zlib=True
    )
    temperature_at_lidar_station = nc.createVariable(
        "Temperature_at_Lidar_Station", "f8", dimensions=(), zlib=True
    )

    # define measurement_cycles
    start_first_measurement = 0
    stop_first_measurement = 12

    # Fill Variables with Data. (mandatory)
    id_timescale[:] = np.array([0, 0, 0, 0])
    laser_pointing_angle[:] = 5
    laser_pointing_angle_of_profiles[:, :] = 0.0
    laser_shots[0, :] = np.array([600, 600, 600, 600])
    laser_shots[1, :] = np.array([600, 600, 600, 600])
    laser_shots[2, :] = np.array([600, 600, 600, 600])
    background_low[:] = np.array([0, 0, 0, 0])
    background_high[:] = np.array([249, 249, 249, 249])
    molecular_calc[:] = 0
    pol_calib_range_min_var[:] = np.repeat(pol_calib_range_min, 4)
    pol_calib_range_max_var[:] = np.repeat(pol_calib_range_max, 4)
    pressure_at_lidar_station[:] = location.pressure
    temperature_at_lidar_station[:] = location.temperature

    # Define total and cross channels IDs from Polly
    if wavelength == Wavelength.NM_355:
        total_channel = location.total_channel_355_nm
        cross_channel = location.cross_channel_355_nm
        channel_id[:] = np.array(location.calibration_355nm_channel_ids)
        nc.Measurement_ID = measurement_id + "35"
        nc.X_PollyXTPipelines_Configuration_ID = (
            location.calibration_configuration_355nm
        )
    elif wavelength == Wavelength.NM_532:
        total_channel = location.total_channel_532_nm
        cross_channel = location.cross_channel_532_nm
        channel_id[:] = np.array(location.calibration_532nm_channel_ids)
        nc.Measurement_ID = measurement_id + "53"
        nc.X_PollyXTPipelines_Configuration_ID = (
            location.calibration_configuration_532nm
        )
    else:
        raise ValueError(f"Unknown wavelength {wavelength}")

    # Copy calibration cycles
    for meas_cycle in range(0, 3, 1):
        laser_shots[meas_cycle, :] = np.array([600, 600, 600, 600])

        raw_data_start_time[meas_cycle, 0] = start_first_measurement + meas_cycle
        raw_data_stop_time[meas_cycle, 0] = stop_first_measurement + meas_cycle

        raw_lidar_data[meas_cycle, 0, :] = pf.raw_signal_swap[
            start_first_measurement + meas_cycle, cross_channel, :
        ]
        raw_lidar_data[meas_cycle, 1, :] = pf.raw_signal_swap[
            start_first_measurement + meas_cycle, total_channel, :
        ]
        raw_lidar_data[meas_cycle, 2, :] = pf.raw_signal_swap[
            stop_first_measurement + meas_cycle, cross_channel, :
        ]
        raw_lidar_data[meas_cycle, 3, :] = pf.raw_signal_swap[
            stop_first_measurement + meas_cycle, total_channel, :
        ]

    # Close the netCDF file.
    nc.close()

    return measurement_id, output_filename


def convert_pollyxt_file(
    repo: pollyxt.PollyXTRepository,
    output_path: Path,
    location: Location,
    interval: timedelta,
    atmosphere: Atmosphere,
    should_round=False,
    calibration=True,
    start_time=None,
    end_time=None,
):
    """
    Converts a pollyXT repository into a collection of SCC files. The input files will be split/merged into intervals
    before being converted to the new format.

    This function is a generator, so you can use it in a for loop to monitor progress:

        for measurement_id, path, start_time, end_time in convert_pollyxt_file(...):
            # Do something with id/path, maybe print a message?


    Parameters:
        repo: PollyXT file to convert
        output_path: Directory to write the SCC files
        location: Geographical information, where the measurement took place
        interval: What interval to use when splitting the PollyXT file (e.g. 1 hour)
        atmosphere: Which atmosphere to use on SCC
        should_round: If true, the interval starts will be rounded down. For example, from 01:02 to 01:00.
        calibration: Set to False to disable generation of calibration files.
        start_hour: Optionally, set when the first file should start. The intervals will start from here. (HH:MM or YYYY-MM-DD_HH:MM format, string)
        end_hour: Optionally, also set the end time. Must be used with `start_hour`. If this is set, only one output file
                  is generated, for your target interval (HH:MM or YYYY-MM-DD_HH:MM format, string).
    """

    # Open input netCDF
    measurement_start, measurement_end = repo.get_time_period()

    # Handle start/end time
    if start_time is not None:
        start_time = utils.date_option_to_datetime(measurement_start, start_time)

        if start_time < measurement_start or measurement_end < start_time:
            raise TimeOutsideFile(measurement_start, measurement_end, start_time)

        measurement_start = start_time

    if start_time is None and end_time is not None:
        raise ValueError("Can't use end_hour without start_hour")

    if end_time is not None:
        end_time = utils.date_option_to_datetime(measurement_end, end_time)

        if end_time < measurement_start or measurement_end < start_time:
            raise TimeOutsideFile(measurement_start, measurement_end, end_time)

        measurement_end = end_time
        interval = timedelta(seconds=(end_time - start_time).total_seconds())

    # Create output files
    interval_start = measurement_start
    while interval_start < measurement_end:
        # If the option is set, round down hours
        if should_round:
            interval_start = interval_start.replace(microsecond=0, second=0, minute=0)

        # Interval end
        interval_end = interval_start + interval

        # Open netCDF file and convert to SCC
        try:
            pf = repo.get_pollyxt_file(
                interval_start, interval_end + timedelta(seconds=30)
            )
            id, path = create_scc_netcdf(pf, output_path, location, atmosphere)

            yield id, path, pf.start_date, pf.end_date
        except NoMeasurementsInTimePeriod as ex:
            # Go to next loop
            interval_start = interval_end
            continue

        # Set start of next interval to the end of this one
        interval_start = interval_end

    # Generate calibration files
    if calibration:
        # Check for any valid calibration intervals
        for start, end in repo.get_calibration_periods():
            if start > measurement_start and end < measurement_end:
                pf = repo.get_pollyxt_file(start, end)

                id, path = create_scc_calibration_netcdf(
                    pf, output_path, location, wavelength=Wavelength.NM_532
                )
                yield id, path, start, end

                id, path = create_scc_calibration_netcdf(
                    pf, output_path, location, wavelength=Wavelength.NM_355
                )
                yield id, path, start, end
