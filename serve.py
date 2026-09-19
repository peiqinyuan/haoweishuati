# -*- coding: utf-8 -*-
"""生产服务器入口（Linux/服务器用，替代 debug 模式）

用法:
    初始化 + 启动:  python serve.py
    仅初始化数据库:  python serve.py --init-only
"""
import os
import sys

if __name__ == '__main__':
    from waitress import serve

    from app import app
    from init_db import init_database

    print('* 正在初始化/校验数据库...')
    result = init_database(app)
    print('* 初始化结果:', result.get('status'), '| 本次导入题数:', result.get('total'))

    if '--init-only' in sys.argv:
        print('* 数据库初始化完成，退出。')
        sys.exit(0)

    port = int(os.environ.get('PORT', '8000'))
    host = os.environ.get('HOST', '0.0.0.0')
    print(f'* 浩威刷题平台已启动: http://{host}:{port}')
    serve(app, host=host, port=port, threads=8)