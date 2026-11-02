import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer

from kmenu_manager.menu_cache import MenuCacheRefresher


app = QCoreApplication([])

with tempfile.TemporaryDirectory() as temp_dir:
    temp = Path(temp_dir)
    counter = temp / "counter"
    fake_command = temp / "kbuildsycoca6"

    fake_command.write_text(
        "#!/bin/sh\n"
        f"echo run >> '{counter}'\n"
        "sleep 0.4\n",
        encoding="utf-8",
    )
    fake_command.chmod(0o755)

    os.environ["PATH"] = f"{temp}:{os.environ['PATH']}"

    refresher = MenuCacheRefresher()
    results = []

    refresher.refresh_finished.connect(
        lambda success, error: results.append((success, error))
    )

    # 连续请求应被防抖合并
    refresher.request_refresh()
    QTimer.singleShot(300, refresher.request_refresh)
    QTimer.singleShot(500, refresher.request_refresh)

    # 第一次进程运行期间再发出多个请求，应合并为一次后续刷新
    QTimer.singleShot(1900, refresher.request_refresh)
    QTimer.singleShot(1950, refresher.request_refresh)
    QTimer.singleShot(2000, refresher.request_refresh)

    def finish_test():
        count = len(counter.read_text().splitlines()) if counter.exists() else 0
        print(f"模拟命令启动次数：{count}")
        print(f"刷新结果数量：{len(results)}")
        print(f"刷新结果：{results}")

        if count == 2 and len(results) == 2 and all(ok for ok, _ in results):
            print("测试通过：防抖与请求合并正常")
        else:
            print("测试未通过：需要进一步检查")

        app.quit()

    QTimer.singleShot(4000, finish_test)
    app.exec()
