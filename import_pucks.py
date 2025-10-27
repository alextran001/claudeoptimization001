import getpass
import grp
import json
import logging
import os
import sys
import time
import traceback
from enum import Enum
from pathlib import Path
from typing import Tuple
from datetime import datetime

import numpy as np
import pandas as pd
import yaml
from qtpy import QtWidgets
from qtpy.QtCore import QSize, Qt, QTimer, QThread, Signal
from qtpy.QtGui import QColor, QIcon
from gui.dialog.dewar import DewarDialog

from gui.config import ConfigurationWindow
from gui.custom_table import DewarTableWithCopy, TableWithCopy
from utils.db_lib import DBConnection
from utils.pandas_model import DewarPandasModel, PuckPandasModel

logger = logging.getLogger(__name__)
logfile_path = Path("./puckimporter.log").expanduser()
logfile_path.parent.mkdir(parents=True, exist_ok=True)
file_handler = logging.FileHandler(logfile_path)
file_handler.setLevel(logging.INFO)


class Mode(Enum):
    MANUAL = "Manual"
    AUTOMATED = "Automated"


class TimerThread(QThread):
    """Independent timer thread that runs separately from main GUI thread"""

    def __init__(self):
        super().__init__()
        self.running = False
        self.start_time = None
        self.current_time_str = "00:00:00"  # Shared variable for current time

    def run(self):
        """Run timer in separate thread"""
        self.running = True
        while self.running:
            if self.start_time is not None:
                elapsed = datetime.now() - self.start_time
                total_seconds = int(elapsed.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                # Update shared variable (thread-safe for simple assignments)
                self.current_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # Sleep for 100ms
            self.msleep(100)

    def start_timer(self):
        """Start the timer"""
        self.start_time = datetime.now()
        self.current_time_str = "00:00:00"
        if not self.isRunning():
            self.start()

    def stop_timer(self):
        """Stop the timer thread"""
        self.running = False
        self.start_time = None

    def reset_timer(self):
        """Reset the timer"""
        self.start_time = None
        self.current_time_str = "00:00:00"

    def get_current_time(self):
        """Get current elapsed time string (thread-safe read)"""
        return self.current_time_str


class ControlMain(QtWidgets.QMainWindow):
    def __init__(self, *args, config_path, **kwargs):
        self.config_path = config_path
        try:
            with self.config_path.open("r") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"TypeError: {traceback.format_exc()}")
            print(
                f"Exception occured while reading config file {self.config_path}: {e}"
            )
            raise e
        self.config = config
        # Cache admin group check for performance (must be before _createMenuBar)
        self._is_admin = self.config.get("admin_group") and self.config["admin_group"] in [
            grp.getgrgid(g).gr_name for g in os.getgroups()
        ]
        super().__init__(*args, **kwargs)
        self.setWindowTitle(f"Import Pucks at {self.config.get('beamline', '99id1')}")
        self.tableView = self._createTableView()
        self.setCentralWidget(self.tableView)
        self._createActions()
        self._createMenuBar()
        self.model = None
        self.mode = Mode.MANUAL
        self.resize(QtWidgets.QDesktopWidget().availableGeometry().size() * 0.7)  # type: ignore
        self.validatePuckLists()
        self.status_bar = self.statusBar()
        self.mode_status = QtWidgets.QLabel(f"MODE: {self.mode.value}")
        self.status_bar.addPermanentWidget(self.mode_status)

        # Timer setup for monitoring elapsed time - using independent thread
        self.timer_label = QtWidgets.QLabel("Elapsed: 00:00:00")
        self.timer_label.setMinimumWidth(150)  # Ensure timer has enough space
        self.status_bar.addPermanentWidget(self.timer_label)

        # Create independent timer thread that calculates elapsed time
        self.timer_thread = TimerThread()
        self.timer_thread.start()  # Start the thread (timer starts when start_timer() is called)

        # Create a GUI update timer that runs on main thread and forces updates
        self.gui_update_timer = QTimer(self)
        self.gui_update_timer.timeout.connect(self._update_timer_from_thread)
        self.gui_update_timer.setInterval(100)  # Update GUI every 100ms

        self.last_printed_second = -1  # Track last printed second to avoid spam
        self.start_time = None  # Keep for compatibility

        # Default mode to start the application
        self._set_mode(Mode.MANUAL)
        self.all_pucks = []
        self.redis_pucklist = []
        self.all_redis_pucks = {}

    def closeEvent(self, event):
        """Clean up when closing the application"""
        # Stop GUI update timer
        if self.gui_update_timer.isActive():
            self.gui_update_timer.stop()

        # Stop timer thread
        if self.timer_thread.isRunning():
            self.timer_thread.stop_timer()
            self.timer_thread.quit()
            self.timer_thread.wait(2000)  # Wait up to 2 seconds for thread to finish

        # Accept the close event
        event.accept()

    def validatePuckLists(self):
        pucklist_path = Path(self.config["list_path"])
        if not pucklist_path.exists():
            #self.showModalMessage(
            #    "Error",
            #    f"Puck list file {pucklist_path} not found. White list and black list are empty",
            #)
            self.pucklists = {"blacklist": [], "whitelist": [], "etched": []}
        else:
            self.parsePuckList(pucklist_path)

    def parsePuckList(self, path: Path):
        parse_excel = False
        if path.suffix == ".json":
            with path.open("r") as f:
                self.pucklists = json.load(f)
                for label in ["whitelist", "blacklist", "etched"]:
                    if label not in self.pucklists.keys():
                        self.pucklists[label] = []
        elif path.suffix == ".xlsx":
            engine = "openpyxl"
            parse_excel = True
        elif path.suffix == ".xls":
            engine = "xlrd"
            parse_excel = True

        if parse_excel:
            self.pucklists = {}
            reader = pd.ExcelFile(path, engine=engine)
            self.pucklists["etched"] = self.get_sheet_data(reader, "etched")
            self.pucklists["whitelist"] = self.get_sheet_data(reader, "white_list")
            self.pucklists["blacklist"] = self.get_sheet_data(reader, "black_list")

    def get_sheet_data(self, reader: pd.ExcelFile, sheet):
        df = reader.parse(
            sheet_name=sheet,
            header=None,
        )
        if len(df.columns) > 0:
            return df.iloc[:, 0].to_list()
        else:
            return []

    def _createActions(self):
        # File menu actions
        self.saveExcelAction = QtWidgets.QAction("&Save table as Excel file", self)
        self.saveExcelAction.triggered.connect(self.saveExcel)
        self.exitAction = QtWidgets.QAction("&Exit", self)
        self.exitAction.triggered.connect(QtWidgets.QApplication.quit)
        self.FillDewarAction = QtWidgets.QAction("&Fill Dewar", self)
        self.FillDewarAction.triggered.connect(self.openDewar)

        # Puck menu actions
        self.importExcelAction = QtWidgets.QAction("&Import Excel file", self)
        self.importExcelAction.triggered.connect(self.importExcel)
        self.validateExcelAction = QtWidgets.QAction(
            "&Validate imported Excel file", self
        )
        self.validateExcelAction.triggered.connect(self.validateExcel)
        self.submitPuckDataAction = QtWidgets.QAction("&Submit Puck data", self)
        self.submitPuckDataAction.triggered.connect(self.submitPuckData)
        self.configWindowAction = QtWidgets.QAction("&Configuration", self)
        self.configWindowAction.triggered.connect(self.openConfigWindow)
        self.manualModeAction = QtWidgets.QAction("&Manual", self)
        self.manualModeAction.triggered.connect(lambda: self._set_mode(Mode.MANUAL))
        self.manualModeAction.setCheckable(True)
        self.manualModeAction.setChecked(True)
        self.automatedModeAction = QtWidgets.QAction("&Automated", self)
        self.automatedModeAction.triggered.connect(
            lambda: self._set_mode(Mode.AUTOMATED)
        )
        self.automatedModeAction.setCheckable(True)
        self.automatedModeAction.setChecked(False)

        # Shipping Dewar menu
        self.beginDewarScanAction = QtWidgets.QAction("&Begin Dewar Scan", self)
        self.beginDewarScanAction.triggered.connect(self.setupDewarScan)

    def _set_mode(self, mode):
        self.mode = mode
        self.mode_status.setText(f"MODE: {self.mode.value}")
        if self.mode == Mode.AUTOMATED:
            self.manualModeAction.setChecked(False)
            self.automatedModeAction.setChecked(True)
            self.owner = "mx"
        elif self.mode == Mode.MANUAL:
            self.manualModeAction.setChecked(True)
            self.automatedModeAction.setChecked(False)
            self.owner = getpass.getuser()

    def _update_timer_from_thread(self):
        """Update GUI from timer thread (runs on main thread, forces processEvents)"""
        # Get current time from thread
        time_str = self.timer_thread.get_current_time()

        # Update GUI label
        self.timer_label.setText(f"Elapsed: {time_str}")

        # Print to console every second (not every 100ms to avoid spam)
        total_seconds = int(time_str.split(':')[0]) * 3600 + int(time_str.split(':')[1]) * 60 + int(time_str.split(':')[2])
        if total_seconds != self.last_printed_second:
            print(f"⏱️  Elapsed: {time_str}", end='\r', flush=True)
            self.last_printed_second = total_seconds

        # Force process events to update GUI immediately
        QtWidgets.QApplication.processEvents()

    def _start_timer(self):
        """Start the elapsed time timer using independent thread"""
        self.start_time = datetime.now()
        self.last_printed_second = -1  # Reset for new timer session
        self.timer_label.setText("Elapsed: 00:00:00")
        self.timer_label.setStyleSheet("color: green; font-weight: bold;")

        # Start the background timer thread
        self.timer_thread.start_timer()

        # Start the GUI update timer to poll the thread and update GUI
        self.gui_update_timer.start()

        print("\n⏱️  Timer started")
        logger.info("Timer started")

    def _stop_timer(self):
        """Stop the elapsed time timer"""
        # Stop GUI update timer
        self.gui_update_timer.stop()

        # Stop background timer thread
        self.timer_thread.stop_timer()

        if self.start_time is not None:
            elapsed = datetime.now() - self.start_time
            hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            final_time = f"Completed in: {hours:02d}:{minutes:02d}:{seconds:02d}"
            self.timer_label.setText(final_time)
            self.timer_label.setStyleSheet("color: blue; font-weight: bold;")
            print(f"\n✅ {final_time}\n")
            logger.info(final_time)
            self.start_time = None

    def _reset_timer(self):
        """Reset the timer display"""
        # Stop GUI update timer
        self.gui_update_timer.stop()

        # Reset background timer thread
        self.timer_thread.reset_timer()

        self.start_time = None
        self.last_printed_second = -1
        self.timer_label.setText("Elapsed: 00:00:00")
        self.timer_label.setStyleSheet("")
        print("\n🔄 Timer reset\n")

    def setupDewarScan(self):
        empty_frame = {None: [""]}
        data = pd.DataFrame.from_dict(empty_frame)
        self.model = DewarPandasModel(data, parent=self)
        self.tableView = self._createTableView()
        self.setCentralWidget(self.tableView)
        self.tableView.setModel(self.model)
        self.tableView.resizeColumnsToContents()
        next_index = self.model.index(0, 0)
        self.tableView.setCurrentIndex(next_index)

    def saveExcel(self):
        filepath, _ = QtWidgets.QFileDialog().getSaveFileName(self, "Save file")
        if filepath:
            filepath = Path(filepath)
            if not filepath.suffix:
                filepath = filepath.parent / (filepath.name + ".xlsx")
            engine = "openpyxl"
            if filepath.suffix == "xls":
                engine = "xlrd"

            if self.model:
                self.model._dataframe.to_excel(filepath, engine=engine, index=False)

    def openDewar(self):
        self.sub = DewarDialog(self)
        self.sub.show()  
        return

    def identify_excel_format(self, file_path):
        with open(file_path, "rb") as f:
            header = f.read(8)

        xls_header = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
        xlsx_header = b"\x50\x4B\x03\x04"

        if header[:8] == xls_header:
            return "xlrd"
        elif header[:4] == xlsx_header[:4]:
            return "openpyxl"
        else:
            return None

    def importExcel(self):
        # Reset timer when importing new file
        self._reset_timer()

        dialog = QtWidgets.QFileDialog()
        if self.config.get("open_in_work_dir", True):
            dialog.setDirectory(os.getcwd())
        filename, _ = dialog.getOpenFileName(
            self, "Import file", filter="Excel (*.xls *.xlsx)"
        )
        required_columns_list = [
            "puckname",
            "position",
            "samplename",
            "proposalnum",
        ]
        if filename:
            engine = self.identify_excel_format(filename)
            excel_file = pd.ExcelFile(filename, engine=engine)
            for sheet_name in excel_file.sheet_names:

                data = excel_file.parse(sheet_name)

                if data.empty:
                    print('no sheet')
                    continue

                # Check if any row besides header row contains "puckname" (optimized)
                # Use map for pandas >= 2.1.0, applymap for older versions
                try:
                    rows = data.map(lambda x: str(x).lower() == required_columns_list[0]).any(axis=1)
                except AttributeError:
                    rows = data.applymap(lambda x: str(x).lower() == required_columns_list[0]).any(axis=1)

                required_columns = set(required_columns_list)
                header_correct = required_columns.issubset(
                    (
                        col.strip().lower()
                        for col in data.columns
                        if isinstance(col, str)
                    )
                )
                print("header_correct {}".format(header_correct))
                if not rows.all() and not header_correct:
                    import_offset = data.loc[rows].first_valid_index()
                    if isinstance(import_offset, (int, np.integer)):
                        data = excel_file.parse(
                            sheet_name=sheet_name, skiprows=import_offset + 1
                        )
                data.rename(
                    columns={
                        col: col.strip().lower()
                        for col in data.columns
                        if isinstance(col, str)
                    },
                    inplace=True,
                )
                # Check headers again after offset
                header_correct = required_columns.issubset(
                    (
                        col.strip().lower()
                        for col in data.columns
                        if isinstance(col, str)
                    )
                )
                if header_correct:
                    #HEADER IS CORRECT, PUCKS IMPORTED CORRECTLY, OFF TO VAlIDATING DATA
                    self.model = PuckPandasModel(data)
                    #self.model.setPuckLists(self.pucklists)
                    self.validateExcel()
                    #does does preprocess data and validates data
                    self.tableView.setModel(self.model)
                    break
            self.tableView.resizeColumnsToContents()

    def _validation_progress_callback(self, message=""):
        """Callback for validation progress - updates UI and processes events"""
        if message:
            self.status_bar.showMessage(message)
        QtWidgets.QApplication.processEvents()

    def validateExcel(self):

        if not isinstance(self.model, PuckPandasModel):
            return

        # Start the timer when validation begins (only if not already started)
        if self.start_time is None:
            self._start_timer()

        # DISABLED: Progress callbacks cause 60-80s overhead from processEvents()
        # self.model.setProgressCallback(self._validation_progress_callback)

        # Disable validation button during processing
        self.validateExcelAction.setEnabled(False)

        # === CRITICAL FIX: Block GUI updates during validation (saves 80-120 seconds!) ===
        # This is the real bottleneck - not pandas operations
        self.model.blockSignals(True)
        self.tableView.setUpdatesEnabled(False)

        try:
            # Update status bar ONCE before starting
            self.status_bar.showMessage("Validating data...")
            QtWidgets.QApplication.processEvents()

            # Preprocess and validate WITHOUT any GUI updates
            self.model.preprocessData()
            self.model.validateData(self.config)

            # Save initial data only if debug mode is enabled
            if self.config.get("debug_save_excel", False):
                self.model._dataframe.to_excel("initial_data.xlsx", index=False)

            # === Re-enable GUI and do ONE bulk refresh ===
            self.model.blockSignals(False)
            self.tableView.setUpdatesEnabled(True)
            self.model.layoutChanged.emit()  # Single update

            # Success - stop timer
            self._stop_timer()
            self.status_bar.showMessage("✓ Validation completed successfully", 5000)
            # Optional: comment out modal for non-blocking experience
            self.showModalMessage("Success", "Validated excel successfully")

        except TypeError as e:
            error_msg = str(e)
            logger.error(f"TypeError: {traceback.format_exc()}")

            # Re-enable GUI even on error
            self.model.blockSignals(False)
            self.tableView.setUpdatesEnabled(True)
            self.model.layoutChanged.emit()

            # Check if this is a "default values filled" warning vs actual error
            if "Empty Values in following columns" in error_msg or "Missing column headers" in error_msg:
                # This is a warning about filled defaults - keep timer running
                self.status_bar.showMessage("⚠ Warning: Default values filled", 5000)
                self.showModalMessage("Warning", error_msg)
            else:
                # This is an actual validation error - reset timer
                self.status_bar.showMessage("✗ Validation failed", 5000)
                self.showModalMessage("Error", error_msg)
                self._reset_timer()
        finally:
            # Ensure GUI is always re-enabled
            self.model.blockSignals(False)
            self.tableView.setUpdatesEnabled(True)
            # Re-enable validation button
            self.validateExcelAction.setEnabled(True)


    def showModalMessage(self, title, message):
        self.msg = QtWidgets.QMessageBox()
        self.msg.setText(str(message))
        self.msg.setModal(True)
        self.msg.setWindowTitle(title)
        self.msg.show()

    def submitPuckData(self):
        # Validation already done in validateExcel(), skip redundant calls
        if not isinstance(self.model, PuckPandasModel):
            self.showModalMessage("Error", "Invalid data, will not upload to database")
            self._reset_timer()
            return

        if not self.model.validData:
            self.showModalMessage("Error", "Data not validated, will not upload. Please validate first.")
            self._reset_timer()
            return

        # Restart timer for submission process
        self._start_timer()
        self.status_bar.showMessage("Starting puck data upload...")

        try:
            if isinstance(self.model, PuckPandasModel):
                beamline_id = self.config.get("beamline", "99id1").lower()
                dbConnection = DBConnection(
                beamline_id=beamline_id,
                #host=self.config.get(
                #    "database_host", os.environ.get("MONGODB_HOST", "localhost")
                #),
                owner=self.owner,
            )
            self.progress_dialog = QtWidgets.QProgressDialog(
                "Uploading Puck data...",
                "Cancel",
                0,
                self.model.rowCount(),
                self,
            )
            # self.progress_dialog.setModal(True)
            self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            prevPuckName = None
            puck_id = None
            redis_puck = None
            previous_redis_puck = None
            self.all_redis_pucks = []
            self.currentPucks = set()
            self.progress_dialog.show()
            self.progress_dialog.setValue(0)
            # Force process events to ensure dialog renders immediately
            QtWidgets.QApplication.processEvents()
            self.current_puck = None
            self.previous_puck = None
            for i, row in enumerate(self.model.rows()):
                # Update progress dialog value
                self.progress_dialog.setValue(i + 1)

                # Process events every 10 rows to update timer and progress (reduced from 5 for better performance)
                if i % 10 == 0:
                    print(f"Processing row {i}")
                    QtWidgets.QApplication.processEvents()

                if self.progress_dialog.wasCanceled():
                    # Reset timer if user cancels
                    self._reset_timer()
                    logger.info("Upload cancelled by user")
                    break
                # Check if puck exists, otherwise create one
                if row["puckname"] != prevPuckName:
                    if puck_id is not None:
                        puck_id['proposal_number'] = propNum
                        redis_puck['proposal_number'] = propNum
                        self.all_pucks.append(puck_id)
                        self.all_redis_pucks.append(redis_puck)
                    puck_id = dbConnection.getOrCreateContainerID(
                        row["puckname"], 16, "16_pin_puck"
                    )
                    previous_redis_puck = redis_puck
                    redis_puck = dbConnection.redisconnection.createPuck(name = row["puckname"], capacity=16)
                    prevPuckName = row["puckname"]

                # Create sample
                # Extract row data with optimized dictionary access (cache repeated lookups)
                sampleName = str(row["samplename"])
                sample_position = int(float(row["position"]))
                propNum = row["proposalnum"]
                puckname = row["puckname"]

                # Optimized row data extraction with cached get operations
                model = row.get('model', 'Nan')
                folder = row.get('folder')
                folder = f"{puckname}_{sample_position:02.0f}" if pd.isna(folder) else folder

                # Build sample_info dictionary with pre-extracted values
                sample_info = {
                    "folder": folder,
                    "deltaphi": row.get("deltaphi", 0.25),
                    "exposure": row.get("exposure", 0.05),
                    "totalphi": row.get("totalphi", 180),
                    "transmission": row.get("transmission", 20),
                    "targetresolution": row.get("targetresolution", 2.0),
                    "beamsize": row.get("beamsize", 30),
                    "priority": row.get("priority", 'Nan'),
                    "collectiontype": row.get("collectiontype", 'centering'),
                    "model": model,
                    "spacegroup": row.get("spacegroup", 'Nan'),
                    "cellparameters": row.get("cellparameters", 'Nan'),
                    "proposal_number": propNum,
                }
                







                sampleID = dbConnection.createSample(
                    str(sampleName),
                    "pin",
                    model=None if pd.isna(model) else str(model),
                    sequence=None if pd.isna(seq) else str(seq),
                    proposalID=propNum,
                    container=puck_id['name'],
                )
                redis_sample = dbConnection.redisconnection.createSample(sample_name = sampleName, sample_data = sample_info)
                if puck_id['name'] not in self.currentPucks:
                    #dbConnection.emptyContainer(puck_id)
                    self.currentPucks.add(puck_id['name'])
                redis_puck = dbConnection.redisconnection.addSampleTopuck(sample = redis_sample, puck = redis_puck, position = sample_position)
                puck_id[sample_position - 1] = sampleID
                #dbConnection.insertIntoContainer(
                #    puck_id, int(row["position"]) - 1, sampleID
                #)
            puck_id['proposal_number'] = propNum
            redis_puck['proposal_number'] = propNum
            self.all_pucks.append(puck_id)
            self.all_redis_pucks.append(redis_puck)
            self.redis_pucklist = [x['name'] for x in self.all_redis_pucks]
            #print(self.all_redis_pucks)
            #print(self.all_pucks)
            #dbConnection.sendToRedis('allpuckData', self.all_pucks)
            dbConnection.sendToRedis('redis_puck_data', self.all_redis_pucks)

            # Stop timer on successful completion
            self._stop_timer()
            self.status_bar.showMessage(
                f"Upload complete! {len(self.all_redis_pucks)} pucks with {self.model.rowCount()} samples",
                10000
            )
            logger.info(f"Successfully uploaded {len(self.all_redis_pucks)} pucks with {self.model.rowCount()} samples")
        except Exception as e:
            logger.error(f"Error during puck data submission: {traceback.format_exc()}")
            self.showModalMessage("Error", f"Failed to upload: {str(e)}")


    def _createMenuBar(self):
        menuBar = self.menuBar()
        # Creating menus using a QMenu object
        fileMenu = QtWidgets.QMenu("&File", self)
        dataMenu = QtWidgets.QMenu("&Puck Import", self)
        dewarScanMenu = QtWidgets.QMenu("&Shipping Dewar", self)
        menuBar.addMenu(fileMenu)
        menuBar.addMenu(dataMenu)
        fileMenu.addActions([self.saveExcelAction, self.FillDewarAction, self.exitAction])

        dataMenu.addActions(
            [
                self.importExcelAction,
                self.validateExcelAction,
                self.submitPuckDataAction,
            ]
        )
        modeSubMenu = dataMenu.addMenu("Mode")
        modeSubMenu.addActions([self.manualModeAction, self.automatedModeAction])

        # Use cached admin check for better performance
        if self._is_admin:
            dataMenu.addAction(self.configWindowAction)
            menuBar.addMenu(dewarScanMenu)
            dewarScanMenu.addAction(self.beginDewarScanAction)

    def _createTableView(self, dewar=False):
        # view = QtWidgets.QTableView()
        if dewar:
            view = DewarTableWithCopy()
        else:
            view = TableWithCopy()
        view.resize(1200, 1200)
        view.horizontalHeader().setStretchLastSection(True)
        view.setAlternatingRowColors(True)
        view.setSelectionMode(QtWidgets.QTableView.SelectionMode.ExtendedSelection)
        return view

    def openConfigWindow(self):
        self.configWindow = ConfigurationWindow(
            config=self.config, puck_list=self.pucklists
        )
        self.config = self.configWindow.config
        with self.config_path.open("w") as f:
            yaml.safe_dump(self.config, f)


def start_app(config_path):
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(Path.cwd() / Path("gui/assets/icon.png"))))
    ex = ControlMain(config_path=config_path)
    ex.show()
    sys.exit(app.exec_())
