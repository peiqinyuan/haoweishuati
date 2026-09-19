#!/usr/bin/env bash
# 浩威刷题 Ubuntu 一键部署脚本
# 用法：
#   把项目整个文件夹上传到服务器 -> 在项目目录里执行:
#       bash deploy.sh
#   脚本会拷贝到 /opt/haowei、装依赖、初始化数据库、并以 systemd 服务常驻运行
set -euo pipefail

PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${1:-/opt/haowei}"

echo ">> [1/5] 安装系统依赖"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip rsync

echo ">> [2/5] 拷贝程序到 ${APP_DIR}（排除本机数据库/临时文件）"
sudo mkdir -p "${APP_DIR}"
if [ "${PROJ_DIR}" != "${APP_DIR}" ]; then
  sudo rsync -a \
    --exclude 'haowei.db' \
    --exclude 'uploads' \
    --exclude '__pycache__' \
    --exclude 'build' \
    --exclude 'dist' \
    --exclude '*.spec' \
    --exclude 'desktop.py' \
    "${PROJ_DIR}/" "${APP_DIR}/"
fi

echo ">> [3/5] 创建虚拟环境并安装 Python 依赖"
if [ ! -d "${APP_DIR}/venv" ]; then
  sudo python3 -m venv "${APP_DIR}/venv"
fi
sudo "${APP_DIR}/venv/bin/pip" install --upgrade pip
sudo "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo ">> [4/5] 初始化数据库（幂等：首次导入全部 3203 题）"
sudo "${APP_DIR}/venv/bin/python" "${APP_DIR}/serve.py" --init-only

echo ">> [5/5] 配置并启动 systemd 服务"
if ! command -v openssl >/dev/null 2>&1; then
  sudo apt-get install -y openssl
fi
SECRET="$(openssl rand -hex 24)"
sudo tee /etc/systemd/system/haowei.service > /dev/null <<EOF
[Unit]
Description=浩威刷题平台
After=network.target

[Service]
WorkingDirectory=${APP_DIR}
Environment=SECRET_KEY=${SECRET}
Environment=PORT=8000
Environment=HOST=0.0.0.0
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/serve.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now haowei
sleep 2
sudo systemctl status --no-pager haowei | head -n 8

echo ""
echo "=============================================="
echo " 完成！访问地址:  http://<服务器公网IP>:8000"
echo " 防火墙放行:     sudo ufw allow 8000/tcp"
echo " 查看日志:       sudo journalctl -u haowei -f"
echo " 重启服务:       sudo systemctl restart haowei"
echo "=============================================="
echo "!!! 安全提示: 首次初始化会创建 admin / admin123 账号，"
echo "!!! 请尽快在服务器上删除或改密，否则任何人可登录管理。"