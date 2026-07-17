# 部署说明

本项目推荐部署方式：

- Docker Compose 运行前端和后端容器
- 前端容器仅监听服务器本机 `127.0.0.1:18080`
- 宝塔/Nginx 负责公网 `80/443`、域名和 SSL
- 后端 FastAPI 只在 Docker 内网暴露，不直接开放公网端口

## 1. 本地打包上传

在本机 PowerShell 进入项目目录：

```powershell
cd D:\code\bi.jiajieco.com
tar --exclude=frontend/node_modules --exclude=frontend/dist --exclude=backend/.venv --exclude=backend/__pycache__ --exclude=backend/*.db --exclude=backend/.env -czf bi-deploy.tar.gz .
scp .\bi-deploy.tar.gz root@175.24.186.206:/root/bi-deploy.tar.gz
```

## 2. 服务器解压

SSH 登录服务器后执行：

```bash
mkdir -p /www/wwwroot/bi.jiajieco.com
tar -xzf /root/bi-deploy.tar.gz -C /www/wwwroot/bi.jiajieco.com
cd /www/wwwroot/bi.jiajieco.com
```

## 3. 创建后端环境变量

```bash
cp backend/.env.example backend/.env
openssl rand -hex 32
vi backend/.env
```

需要填写：

```env
DATABASE_URL=sqlite:////app/data/bi_admin.db
ODS_DATABASE_URL=mysql+pymysql://jiajie:<PASSWORD_URL_ENCODED>@175.24.186.206:3306/ods?charset=utf8mb4
SECRET_KEY=<OPENSSL_GENERATED_SECRET>
CORS_ORIGINS=["http://175.24.186.206","http://jiajieco.com","https://jiajieco.com","http://www.jiajieco.com","https://www.jiajieco.com"]
DEMO_USERNAME=admin
DEMO_PASSWORD=<CHANGE_ADMIN_PASSWORD>
OPENAI_TIMEOUT_SECONDS=120
```

注意：MySQL 密码放进 URL 时，特殊字符要转义，例如 `#` 写成 `%23`，`!` 写成 `%21`。

如果使用 AI 决策中心，还需要在页面“系统设置 -> 模型设置”里保存模型地址、模型 ID 和 API Key。模型接口慢时可把 `OPENAI_TIMEOUT_SECONDS` 调到 `180`。

服务器上可以先验证模型网络是否能连通：

```bash
docker compose exec backend python - <<'PY'
from app.core.config import settings
print("timeout:", settings.OPENAI_TIMEOUT_SECONDS)
PY

curl -I --connect-timeout 10 https://你的模型服务域名
```

如果 `curl` 也很慢或超时，说明是服务器到模型服务的网络问题，需要检查模型服务域名、腾讯云出站网络、服务商访问限制或代理配置。

## 4. 启动 Docker

```bash
docker compose up -d --build
docker compose ps
```

如果服务器只支持旧命令：

```bash
docker-compose up -d --build
docker-compose ps
```

验证容器内前端和 API：

```bash
curl -I http://127.0.0.1:18080
curl http://127.0.0.1:18080/api/v1/openapi.json | head
```

## 5. 开放端口

腾讯云安全组开放：

- TCP `80`
- TCP `443`

服务器防火墙执行：

```bash
firewall-cmd --permanent --add-service=http
firewall-cmd --permanent --add-service=https
firewall-cmd --reload
```

如果 `firewall-cmd` 不存在，说明系统防火墙可能未启用，可先跳过，以腾讯云安全组为准。

## 6. 宝塔配置站点

宝塔面板中：

1. 软件商店确认已安装 Nginx
2. 网站 -> 添加站点
3. 域名暂时填写服务器 IP：`175.24.186.206`
4. 创建后进入该站点设置 -> 反向代理
5. 代理名称：`bi`
6. 目标 URL：`http://127.0.0.1:18080`
7. 开启代理

访问：

```text
http://175.24.186.206
```

## 7. 域名备案完成后

1. 腾讯云 DNS 添加 A 记录：
   - `jiajieco.com` -> `175.24.186.206`
   - `www.jiajieco.com` -> `175.24.186.206`
2. 宝塔站点中添加域名：
   - `jiajieco.com`
   - `www.jiajieco.com`
3. 宝塔 SSL 申请 Let's Encrypt
4. 开启强制 HTTPS
5. 重新检查登录和接口请求

## 常用维护命令

```bash
cd /www/wwwroot/bi.jiajieco.com
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose restart
docker compose up -d --build
```
