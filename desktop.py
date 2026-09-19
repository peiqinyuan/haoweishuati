# -*- coding: utf-8 -*-
"""浩威刷题 桌面版（可打包为独立 exe）

- 后台启动本地 Flask 服务
- 用 pywebview 弹出原生桌面窗口加载网站
- 若 pywebview 不可用则自动回退到系统浏览器
- 设置环境变量 HW_TEST_PORT 可进入自动化测试模式（只启动服务不开窗口）

网站版不受影响：直接运行 app.py（python app.py 或 IDE 运行）。
"""
import os
import socket
import threading
import time
import urllib.request
import webbrowser


def find_free_port():
    """获取一个空闲端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_server_ready(url, timeout=30):
    """轮询等待本地服务就绪，防止窗口先于服务打开导致白屏"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    from init_db import init_database
    from app import app

    # 确保数据库表与缺失科目已导入（增量，不覆盖已有题目）
    init_database(app)

    test_port = os.environ.get('HW_TEST_PORT') or os.environ.get('HW_PORT')
    port = int(test_port) if test_port else find_free_port()
    url = f'http://127.0.0.1:{port}'

    def run_server():
        app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)

    server = threading.Thread(target=run_server, daemon=True)
    server.start()
    time.sleep(1.2)
    if not wait_server_ready(url):
        print('* 警告: 本地服务未能及时就绪，窗口可能白屏，请重试或稍候。')
    print('* 浩威刷题 服务已启动:', url)

    def write_mark(text):
        mark = os.environ.get('HW_MARKER')
        if mark:
            try:
                with open(mark, 'w', encoding='utf-8') as f:
                    f.write(text)
            except Exception:
                pass

    # 自动化测试模式：仅启动服务，供外部验证
    if os.environ.get('HW_TEST_PORT'):
        write_mark('server')
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    try:
        import webview
        webview.create_window(
            '浩威刷题',
            url,
            width=1280,
            height=820,
            min_size=(1024, 680)
        )
        write_mark('webview')
        webview.start()
    except Exception as e:
        write_mark('browser')
        print('* pywebview 不可用，改用浏览器打开:', e)
        webbrowser.open(url)
        # 保持后台服务继续运行
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()