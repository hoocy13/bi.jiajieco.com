# GitHub 手动发版说明

目标：

- 代码放到 GitHub 私有仓库
- GitHub Actions 手动触发部署
- 服务器保留线上 `backend/.env`
- 部署成功后自动构建 Docker 并健康检查

## 1. 创建 GitHub 私有仓库

在 GitHub 网页创建一个私有仓库，例如：

```text
bi.jiajieco.com
```

不要勾选自动创建 README、`.gitignore` 或 license。

## 2. 初始化本地 Git 仓库

在本机 cmd 执行：

```bat
cd /d D:\code\bi.jiajieco.com
git init
git branch -M main
git add .
git commit -m "Initial BI project"
git remote add origin https://github.com/<你的GitHub用户名>/bi.jiajieco.com.git
git push -u origin main
```

## 3. 生成部署 SSH Key

在本机 cmd 执行：

```bat
ssh-keygen -t ed25519 -C "github-actions-bi-deploy" -f %USERPROFILE%\.ssh\bi_github_actions
```

一路回车即可。

## 4. 把公钥加入服务器

上传公钥：

```bat
scp %USERPROFILE%\.ssh\bi_github_actions.pub root@175.24.186.206:/root/bi_github_actions.pub
```

登录服务器：

```bat
ssh root@175.24.186.206
```

服务器里执行：

```bash
mkdir -p ~/.ssh
cat /root/bi_github_actions.pub >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
rm -f /root/bi_github_actions.pub
```

## 5. 在 GitHub 添加 Secrets

进入 GitHub 仓库：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

添加 3 个 secret：

```text
TENCENT_HOST = 175.24.186.206
TENCENT_USER = root
TENCENT_SSH_KEY = 本机 %USERPROFILE%\.ssh\bi_github_actions 文件里的全部内容
```

注意：`TENCENT_SSH_KEY` 要填私钥文件内容，不是 `.pub` 文件。

## 6. 手动发版

进入 GitHub 仓库：

```text
Actions -> Deploy BI -> Run workflow -> Run workflow
```

看到：

```text
Frontend health check passed.
Deploy finished.
```

就说明发版成功。

线上地址：

```text
https://bi.jiajieco.com
```

## 7. 以后日常流程

本地改代码后：

```bat
cd /d D:\code\bi.jiajieco.com
git status
git add .
git commit -m "描述这次更新"
git push
```

然后去 GitHub Actions 页面手动点 `Run workflow`。
