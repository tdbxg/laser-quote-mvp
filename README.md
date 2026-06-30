# 激光报价助手

稳定网页/API 部署版。

## 运行

```bash
pip install -r requirements.txt
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

打开：

```text
http://127.0.0.1:8000/
```

## Render 部署

仓库包含 `render.yaml`。在 Render 里选择 New -> Blueprint -> 本仓库，即可部署。

部署后得到的 HTTPS 地址既是网页地址，也是微信小程序 `apiBase`。

## 准确性说明

自动结果只能作为待确认报价。存在警告、跳过实体、重复视图或无报价行时，必须人工复核后才能正式报价。

当前 GitHub API 上传的是可部署精简版；完整本地工程和小程序骨架仍保存在本机项目目录与 zip 包中。
