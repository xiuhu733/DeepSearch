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
python3 ~/.codex/skills/deepseek-web-search/scripts/deepseek_search.py search "DeepSeek API" --count 5 --compact
python3 ~/.codex/skills/deepseek-web-search/scripts/deepseek_search.py fetch "https://api-docs.deepseek.com/zh-cn/guides/search"
```

搜索结果包含摘要和来源链接，可按需请求正文。抓取结果取决于目标网站的可访问性。搜索摘要和排序分数不能代替查阅原文。

`--compact` 只返回标题、链接、摘要和日期，适合减少模型上下文占用；与 `--need-content` 同用时，每条正文最多返回 2000 个字符，并通过 `content_truncated` 标明是否被截断。不使用 `--compact` 时保持 API 原始 JSON 响应。请求出错时，脚本会给出对应的排查提示；为保护 API Key，脚本拒绝 API 重定向。

## 广泛搜索

批量搜索接收调用方指定的查询，不预设查询数量或搜索策略。模型可以根据任务决定查询词、请求数量、是否取正文，以及是否继续搜索；实际返回数量可能少于请求数量。原始结果保存在本地，合并后按 URL 去重，并分批输出候选供模型筛选。例如：

```bash
python3 ~/.codex/skills/deepseek-web-search/scripts/deepseek_batch.py \
  --query "searchable encryption leakage attacks" \
  --query "SSE query recovery attack" \
  --need-content \
  --output-dir "$HOME/.cache/deepseek-web-search/sse-example"
```

输出目录包含缓存，以及每次运行的原始结果、运行记录和候选批次。默认复用 24 小时内相同参数的搜索结果；可用 `--max-age-hours` 调整，或用 `--refresh` 强制重新搜索。每个未命中缓存的查询都可能产生一次 Search 费用；脚本不会自动调用 Fetch。`--need-content` 可请求正文，但正文可能缺失，且结果文件会更大。

调用方可以使用 `--count`、`--batch-size`、`--original-question` 和 `--localization` 自行调整请求和输出；不指定 `--count` 时使用 Search 客户端的默认值。通过 `--help` 查看全部参数。

去重仅针对规范化后的 URL，不会自动合并同一论文的不同版本。筛选结果和摘要不能替代原文核验。搜索词与结果保存在输出目录，请选择适当的私有目录，避免提交到 Git。

## 离线测试

```bash
python3 -m unittest discover -s tests -v
```

测试使用模拟响应，不需要 API Key，不发起网络请求。

Search 和 Fetch 可能产生调用费用；当前接口参数、计费与限速以 [DeepSeek 官方文档](https://api-docs.deepseek.com/zh-cn/guides/search)为准。
