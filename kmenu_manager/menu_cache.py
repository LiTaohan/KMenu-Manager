from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class MenuCacheRefresher(QObject):
    refresh_finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._start_process)

        self._process = QProcess(self)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)

        self._pending = False
        self._error_reported = False

    def request_refresh(self):
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._pending = True
            return

        self._timer.start()

    def _start_process(self):
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._pending = True
            return

        self._error_reported = False
        self._process.start(
            "kbuildsycoca6",
            ["--noincremental"],
        )

    def _on_finished(self, exit_code, exit_status):
        success = (
            exit_status == QProcess.ExitStatus.NormalExit
            and exit_code == 0
        )

        error = "" if success else (
            f"kbuildsycoca6 退出，代码：{exit_code}"
        )
        if not self._error_reported:
            self.refresh_finished.emit(success, error)

        if self._pending:
            self._pending = False
            self._timer.start()

    def _on_error(self, process_error):
        if process_error != QProcess.ProcessError.FailedToStart:
            return

        if not self._error_reported:
            self._error_reported = True
            error = self._process.errorString()
            self.refresh_finished.emit(False, error)

        if self._pending:
            self._pending = False
            self._timer.start()
