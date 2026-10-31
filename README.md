# DeepSearch

一个通过 DeepSeek Search / Fetch API 搜索网页和抓取正文的 Codex skill。使用 Python 3 标准库，无需安装第三方依赖。

## 安装

将 `deepseek-web-search` 目录复制到 `~/.codex/skills/`：

```bash
mkdir -p ~/.codex/skills
cp -R deepseek-web-search ~/.codex/skills/
```

配置 DeepSeek API Key：设置环境变量 `DEEPSEEK_API_KEY`，或者将 Key 存放在 `~/.config/deepseek/api_key` 并将文件权限设为 `600`。环境变量优先。请勿将 Key 提交到仓库。

在 Codex 中调用 `$deepseek-web-search`，或者要求使用 DeepSeek 搜索。新安装后如未识别，可以开启新会话。

## 命令行使用

```bash
python3 ~/.codex/skills/deepseek-web-search/scripts/deepseek_search.py search "DeepSeek API" --count 5 --need-content
python3 ~/.codex/skills/deepseek-web-search/scripts/deepseek_search.py fetch "https://api-docs.deepseek.com/zh-cn/guides/search"
```

搜索结果包含摘要和来源链接，可按需请求正文。抓取结果取决于目标网站的可访问性。搜索摘要和排序分数不能代替查阅原文。

Search 和 Fetch 可能产生调用费用；当前接口参数、计费与限速以 [DeepSeek 官方文档](https://api-docs.deepseek.com/zh-cn/guides/search)为准。
