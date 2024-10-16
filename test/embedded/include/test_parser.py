import os
import csv
import re
from typing import Optional, List, Dict
from platformio.public import TestCase, TestCaseSource, TestStatus


class TestParser:
    """Generates Unity TestCase objects for PlatformIO
    """

    def find_last_modified_test_dir(self) -> Optional[str]:
        """Finds the last modified directory in the 'test/logs' folder.

        Returns:
            Optional[str]: The path of the last modified directory, 
            or None if no directories are found.
        """
        dirs = []
        test_data_directory = os.path.join("test", "logs")

        # Iterate through all items in the base_directory
        for d in os.listdir(test_data_directory):
            dir_path = os.path.join(test_data_directory, d)
            # Check if the item is a directory and add to the list
            if os.path.isdir(dir_path):
                dirs.append(dir_path)

        if not dirs:
            return None

        # Find the directory with the latest modification time
        last_modified_dir = max(dirs, key=os.path.getmtime)

        return last_modified_dir

    def get_timestamped_lines(self) -> Optional[List[Dict[str, float]]]:
        """Get all lines from csv and timestamp the time the last byte was recieved

        Returns:
            list[dict]: A list of dictionaries with line contents and duration
        """

        LATEST_LOG_PATH = self.find_last_modified_test_dir()
        if not LATEST_LOG_PATH:
            print("No test log directories found.")
            return None

        LATEST_DATA_CSV_PATH = os.path.join(LATEST_LOG_PATH, "uart_export.csv")

        if not os.path.exists(LATEST_DATA_CSV_PATH):
            print(f"File '{LATEST_DATA_CSV_PATH}' not found.")
            return None

        timestamped_lines = []

        with open(LATEST_DATA_CSV_PATH, "r") as r:
            reader = csv.reader(r)
            header = next(reader, None)
            if not header:
                print("Empty CSV file or no header row.")
                return None
            try:
                # Get the column indices
                DATA_COL = header.index("data")
                START_TIME_COL = header.index("start_time")
            except ValueError:
                print("Required columns 'data' or 'start_time' not found.")
                return None

            # Flag to avoid storing consecutive newlines
            last_newline = False
            # Current text line (seperated by newline)
            current_line = ""
            # The timestamp of when the last line finished
            last_line_timestamp = 0.0

            # Header row is skipped because the iterator has passed it previously
            for row in reader:
                # Add data collumn which is probably last row
                data = row[DATA_COL]
                if data not in "\n\r":
                    current_line += data
                    last_newline = False
                elif not last_newline:
                    current_line_timestamp = float(row[START_TIME_COL])
                    timestamped_lines.append({
                        "line": current_line,
                        "fall_timestamp": current_line_timestamp
                    })
                    last_line_timestamp = current_line_timestamp
                    current_line = ""
                    last_newline = True
        return timestamped_lines

    def _get_index_of_last_result_line(
        self,
        timestamped_lines: Optional[List[Dict[str, float]]],
        line_index: int
    ):
        """Gets the index of the last result line.
        A result line is in the form `Test\s(\w+)\s(passed|failed)`

        Args:
            timestamped_lines (Optional[List[Dict[str, float]]]): Lines from `get_timestamped_lines()`
            line_index (int): Index of current line to search backwards from.
        """
        REGEX = r"Test\s(\w+)\s(passed|failed)"

        while not re.match(REGEX, timestamped_lines[line_index]):
            line_index -= 1
        return line_index

    def _parse_failure_line(self, line_text: str) -> Optional[dict[str, str]]:
        # Regex to read the line of a failed test
        # Using "AUnitPlatformIO.ino:12: Assertion failed: (3) != (3)."
        # Group 1: File | Example: "AUnitPlatformIO.ino"
        # Group 2: Line | Example: "12"
        # Group 3: Message | Example: "Assertion failed: (3) != (3)."
        FAILURE_REGEX = r"(\w+.(?:cpp|ino)):(\d+):\s(.+)"
        match = re.match(FAILURE_REGEX, line_text)
        if match == None:
            return None
        return {
            "file": match.group(1),
            "line": match.group(2),
            "message": match.group(3),
        }

    def _generate_test_case(
        self,
        timestamped_lines: Optional[List[Dict[str, float]]],
        re_match: re.Match,
        line_index: int
    ):
        # Example: timestamped_lines

        # {'duration': 0.858, 'line': 'TestRunner started on 2 test(s).'},
        # {'duration': 0.002, 'line': 'Test exampleTest1 passed.'},
        # {'duration': 0.004, 'line': 'AUnitPlatformIO.ino:12: Assertion failed: (3) != (3).'},
        # {'duration': 0.002, 'line': 'Test exampleTest2 failed.'},
        # {'duration': 0.003, 'line': 'TestRunner duration: 0.010 seconds.'},
        # {'duration': 0.007,
        # 'line': 'TestRunner summary: 1 passed, 1 failed, 0 skipped, 0 timed out, out '
        #         'of 2 test(s).'}

        # Example: timestamped_lines in text form only

        # TestRunner started on 2 test(s).
        # Test exampleTest1 passed.
        # AUnitPlatformIO.ino:12: Assertion failed: (3) != (3).
        # Test exampleTest2 failed.
        # TestRunner duration: 0.010 seconds.
        # TestRunner summary: 1 passed, 1 failed, 0 skipped, 0 timed out, out

        text_status = re_match.group(2)
        case_test_name = re_match.group(1)
        match text_status:
            case "passed":
                # Duration of a test that passed is the difference of duration of
                # the sucess messsage the end of the last message
                case_duration = \
                    timestamped_lines[line_index]["fall_timestamp"] \
                    - timestamped_lines[line_index-1]["fall_timestamp"]
                case_status = TestStatus.PASSED
                test_case = TestCase(
                    name=case_test_name,
                    status=case_status,
                    duration=0.69  # TODO implement duration
                )
            case "failed":
                case_status = TestStatus.FAILED
                # TODO Implement a scanner and compiler using _get_index_of_last_result_line
                # To find multiple assertions if you use them. For now, assume line_index-1
                parsed_line = self._parse_failure_line(
                    timestamped_lines[line_index-1]["line"]
                )
                if parsed_line == None:
                    raise Exception("Line incorrectly parsed")
                test_case = TestCase(
                    name=case_test_name,
                    status=case_status,
                    message=parsed_line["message"],
                    stdout=timestamped_lines[line_index-1]["line"],
                    duration=0.69,
                    source=TestCaseSource(
                        filename=parsed_line["file"], line=parsed_line["line"]
                    ),
                )
            case _:
                print("Unexpected case_status")

        return test_case

    def create_all_test_cases(self) -> List[TestCase]:
        test_cases = []
        timestamped_lines = self.get_timestamped_lines()

        for index, line in enumerate(timestamped_lines):
            if re_match := re.match(r"Test\s(\w+)\s(passed|failed)", line["line"]):
                test_cases.append(self._generate_test_case(
                    timestamped_lines, re_match, index))

        return test_cases
