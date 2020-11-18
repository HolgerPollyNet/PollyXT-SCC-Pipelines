import logging
import datetime
from pathlib import Path

from cleo import Command
import pandas as pd
from rich.table import Table
from rich.progress import Progress

from pollyxt_pipelines.console import console
from pollyxt_pipelines import scc_access, locations
from pollyxt_pipelines.scc_access import new_api
from pollyxt_pipelines.config import Config
from pollyxt_pipelines.utils import bool_to_emoji


class UploadFiles(Command):
    '''
    Batch upload files to SCC

    scc-upload
        {path : Path to SCC files. If it is a directory, all netCDF files inside will be uploaded.}
        {list? : Optionally, store the uploaded file IDs in order to later download the products using scc-download}
    '''

    def handle(self):
        # Parse arguments
        path = Path(self.argument('path'))
        if path.is_dir:
            files = path.glob('*.nc')
            files = filter(lambda x: not x.name.startswith('rs_'), files)
            files = filter(lambda x: not x.name.startswith('calibration_'),
                           files)  # TODO Handle calibration files
        else:
            files = [path]

        # Read application config
        config = Config()
        try:
            credentials = scc_access.api.SCC_Credentials(config)
        except KeyError:
            self.line('<error>Credentials not found in config</error>')
            self.line('Use `pollyxt_pipelines config` to set the following variables:')
            self.line('- http.username')
            self.line('- http.password')
            self.line('- auth.username')
            self.line('- auth.password')
            self.line('For example, `pollyxt_pipelines config http.username scc_user')
            return 1

        # Upload files
        successful_files = []
        successful_ids = []
        for file, id in scc_access.upload_files(files, credentials):
            self.line(f'<info>Uploaded</info> {file} <info>, got ID = </info>{id}')
            successful_files.append(successful_files)
            successful_ids.append(id)

        # Write list file if requested
        list_file = self.argument('list')
        if list_file is not None:
            list_file = Path(list_file)

            df = pd.DataFrame()
            df['Filename'] = successful_files
            df['Measurement_ID'] = successful_ids
            df['Products_Downloaded'] = False

            df.to_csv(list_file, index=False)
            self.line(f'<comment>Wrote IDs to </comment>{list_file}')


class DownloadFiles(Command):
    '''
    Batch download files from SCC

    scc-download
        {output-directory : Where to store the processing products}
        {list? : Path to list file generated by `scc-upload`. Checks all files and downloads all available products}
        {--id=* : Optionally, instead of a list file, you can write IDs manually.}
    '''

    def handle(self):
        # Check output directory
        output_directory = Path(self.argument('output-directory'))
        output_directory.mkdir(parents=True, exist_ok=True)

        # Check if list or IDs are defined
        id_frame = None
        id_list_file = self.argument('list')
        if id_list_file is None:
            ids = self.option('id')
            if ids is None or len(ids) == 0:
                self.line_error('Either a list file or some measurement IDs must be provided!')
                return 1
        else:
            id_frame = pd.read_csv(id_list_file, index_col='Measurement_ID')
            ids = id_frame.index

        # Read application config
        config = Config()
        try:
            credentials = scc_access.api.SCC_Credentials(config)
        except KeyError:
            self.line('<error>Credentials not found in config</error>')
            self.line('Use `pollyxt_pipelines config` to set the following variables:')
            self.line('- http.username')
            self.line('- http.password')
            self.line('- auth.username')
            self.line('- auth.password')
            self.line('For example, `pollyxt_pipelines config http.username scc_user')
            return 1

        # Download files for each ID
        for id, success in scc_access.download_files(ids, output_directory, credentials):
            if success:
                self.line(f'<info>Downloaded products for </info>{id}')
            else:
                self.line(f'<comment>Processing not finished for </comment>{id}')

            if id_frame is not None:
                id_frame.loc[id, 'Products_Downloaded'] = success


class ProcessFile(Command):
    '''
    Upload a file to SCC, wait for processing and download the results

    scc-process
        {filename : Which file to upload. Must be accompanied by a radiosonde file}
        {download-path : Where to download the results}
    '''

    def handle(self):
        # Parse arguments
        filename = Path(self.argument('filename'))

        download_path = Path(self.argument('download-path'))
        download_path.mkdir(exist_ok=True, parents=True)

        # Read application config
        config = Config()
        try:
            credentials = scc_access.api.SCC_Credentials(config)
        except KeyError:
            self.line('<error>Credentials not found in config</error>')
            self.line('Use `pollyxt_pipelines config` to set the following variables:')
            self.line('- http.username')
            self.line('- http.password')
            self.line('- auth.username')
            self.line('- auth.password')
            self.line('For example, `pollyxt_pipelines config http.username scc_user')
            return 1

        try:
            measurement = scc_access.process_file(filename, download_path, credentials)
        except scc_access.api.WrongCredentialsException:
            self.line_error('<error>Could not authenticate with SCC, verify credentials</error>')
            return 1
        print(measurement)


class SearchSCC(Command):
    '''
    Queries SCC for measurements

    scc-search
        {date-start : First day to return (YYYY-MM-DD)}
        {date-end : Last day to return (YYYY-MM-DD)}
        {location? : Search for measurement from this station}
        {--to-csv= : Optionally, write file list into a CSV file}
    '''

    def handle(self):
        # Parse arguments
        location_name = self.argument('location')
        location = None
        if location_name is not None:
            location = locations.get_location_by_name(location_name)
            if location is None:
                locations.unknown_location_error(location_name)
                return 1

        try:
            date_start = self.argument('date-start')
            date_start = datetime.date.fromisoformat(date_start)
        except ValueError:
            logging.error('Could not parse date-start! Please use the ISO format (YYYY-MM-DD)')
            return 1

        try:
            date_end = self.argument('date-end')
            date_end = datetime.date.fromisoformat(date_end)
        except ValueError:
            logging.error('Could not parse date-start! Please use the ISO format (YYYY-MM-DD)')
            return 1

        # Read application config
        config = Config()
        try:
            credentials = scc_access.api.SCC_Credentials(config)
        except KeyError:
            self.line('<error>Credentials not found in config</error>')
            self.line('Use `pollyxt_pipelines config` to set the following variables:')
            self.line('- http.username')
            self.line('- http.password')
            self.line('- auth.username')
            self.line('- auth.password')
            self.line('For example, `pollyxt_pipelines config http.username scc_user')
            return 1

        # Login to SCC to make queries
        with new_api.scc_session(credentials) as scc:
            with Progress(console=console) as progress:
                task = progress.add_task('Fetching results...', start=False, total=1)

                # Query SCC for measurements
                pages, measurements = scc.query_measurements(
                    date_start, date_end, location, credentials)
                if len(measurements) == 0:
                    progress.stop(task)
                    console.print('[warning]No measurements found![/warning]')
                    return 0

                if pages > 1:
                    progress.start_task(task)
                    progress.update(task, total=pages, completed=1, start=True)

                    current_page = 2
                    while current_page <= pages:
                        _, more_measurements = scc.query_measurements(
                            date_start, date_end, location, page=current_page)
                        measurements += more_measurements

                        current_page += 1
                        progress.advance(task)

        # Render table
        table = Table(show_header=True, header_style="bold")
        for col in ['ID', 'Location', 'Start', 'End',
                    'HiRELPP', 'CloudMask', 'ELPP', 'ELDA', 'ELDEC', 'ELIC', 'ELQUICK', 'Is Processing']:
            table.add_column(col)

        for m in measurements:
            table.add_row(
                m.id,
                m.location.name,
                m.date_start.strftime('%Y-%m-%d %H:%M'),
                m.date_end.strftime('%Y-%m-%d %H:%M'),
                bool_to_emoji(m.has_hirelpp),
                bool_to_emoji(m.has_cloudmask),
                bool_to_emoji(m.has_elpp),
                bool_to_emoji(m.has_elda),
                bool_to_emoji(m.has_eldec),
                bool_to_emoji(m.has_elic),
                bool_to_emoji(m.has_elquick),
                bool_to_emoji(m.is_processing),
            )

        console.print(table)

        # Write to CSV
        csv_path = self.option('to-csv')
        if csv_path is not None:
            csv_path = Path(csv_path)
            with open(csv_path, 'w') as f:
                f.write(
                    'id,station_id,location,date_start,date_end,date_creation,date_updated,hirelpp,cloudmask,elpp,elda,eldec,elic,elquick,is_processing\n')

                for m in measurements:
                    f.write(m.to_csv() + '\n')

            console.print(f'[info]Wrote .csv file[/info] {csv_path}')
