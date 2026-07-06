# 学打匹克球 / Learning Pickleball — 高质量 docx 构建方案 (Design Spec)

- 日期：2026-06-22
- 状态：方向已批准，spec 待评审
- 适用仓库：`learning_pickleball`

## 1. 目标

- 产出两个**出版级 docx**：`learning_pickleball-cn.docx`、`learning_pickleball-en.docx`。
- 内容 100% 来自 `cn/*.md` / `en/*.md`，与 md 始终一致（由“从 md 生成”天然保证，而非人工对齐）。
- 排版达到出版图书标准：封面、版权/版本页、自动目录、章节另起页、统一图注/表格、页眉页脚页码、书籍字体。
- **可重复**：一条命令重建两本；以后每次 md 更新只需重跑。

## 2. 非目标

- 不做印刷厂级极致排版（精确字距/对齐微调）。如需，最后在 Word 人工润色。
- 不修改 md 内容（本方案只生成 docx；内容订正另行处理）。
- 不替换现有 GitBook → PDF 流程；docx 与其并存。

## 3. 输入现状（已核对）

- 章节：`cn/` 与 `en/` 各 **21 章 + 6 附录**；H1=27、H2/H3/H4 = 181/158/12。
- **标题已自带编号**（`第 1 章`、`1.1`、`1.1.1`）→ 模板只做样式，**不**再自动编号（避免重复编号）。
- 图片：`../_images/*.png`，文件齐全；引用约 78 处。
- 表格：15 个章节含 GFM 管道表格；无 mermaid、无块级 raw HTML（pandoc 友好）。
- 章节顺序以 `SUMMARY.md` 为准（附录顺序 ≠ 文件名字母序，必须解析 SUMMARY）。
- 版本：最新 tag `v2.10.0`（HEAD 为其后若干次提交）。
- 封面源：`_images/cover.jpg`（左中文 / 右英文，合在一张图里）。

## 4. 工具与环境

- pandoc 3.9 ✓；`sips`（macOS 自带，用于裁图）；npm ✓（如需 docx-js 做前置页，备选）。
- LibreOffice：**将安装**（`brew install --cask libreoffice`），仅用于把 docx 渲染成 PDF 截图做校对，不参与正式构建链路。
- 字体（均 macOS 自带，保证本机渲染一致）：中文 Songti SC（宋体）/ PingFang SC / Heiti SC；英文 Georgia / Helvetica Neue。

## 5. 锁定的决策（用户已批准默认）

| 项 | 取值 |
|---|---|
| 开本 | 16 开（约 185×260mm） |
| 封面 | 先用 `_images/cover.jpg` 裁中/英两半满版；不够再重排标题页 |
| 中文字体 | 正文宋体 + 标题黑体/苹方 |
| 英文字体 | 正文 Georgia + 标题无衬线 |
| 目录深度 | 到 H3（第 X 章 / 1.1 / 1.1.1） |

## 6. 架构（构建管道）

入口脚本 `tools/build_docx.py`，对每种语言执行：

1. **解析 `SUMMARY.md`**，得到该语言的有序章节文件列表。
2. **pandoc**：所有章节 md → 正文 docx
   - `--reference-doc=tools/docx/reference-<lang>.docx`（样式模板）
   - `--toc --toc-depth=3`（生成可点击、带页码的 Word 目录域）
   - `--resource-path=<仓库根>` 解析 `../_images`
   - **不**使用 `--number-sections`（标题已带号）
3. **前置内容注入**（unpack → 编辑 XML → pack，复用 docx skill 脚本）：
   - 整页封面（满版 `cover-<lang>.png`，无页眉/页脚/页码）
   - 版权 / 版本页
   - （目录由 pandoc 放在正文前，紧随版权页之后）
4. **输出** `learning_pickleball-<lang>.docx` 到仓库根；随后用 LibreOffice 渲染 PDF 截图自检。

## 7. 模板设计（`reference-<lang>.docx`，质量核心）

- **页面**：16 开（DXA ≈ 10488×14740）；镜像页边距便于装订（默认上/下 2.2cm、内 2.2cm、外 1.8cm）。
- **字体 / 正文**：中文 Songti SC 10.5–11pt；英文 Georgia 11pt；行距约 1.3–1.4；两端对齐；段后间距。
- **标题**：`Heading1` 每章**另起页**（page-break-before）、大字号加粗；`Heading2/3/4` 字号递减。中文标题用黑体/苹方，英文用无衬线。
- **图片**：居中；图注样式“图 X-Y …”小字灰色居中。
- **表格**：浅灰描边、表头底色、单元格内边距；不用纯黑底（`ShadingType.CLEAR`）。
- **页眉/页脚**：页眉显示书名（偶页）/ 当前章名（奇页）；页脚页码居中；封面与版权页不显示。
- **目录样式**：点引线 + 页码右对齐。

## 8. 封面与版权页

- 用 `sips` 将 `cover.jpg` 裁成左（中）/ 右（英）两半 → `tools/docx/cover-cn.png` / `cover-en.png`，满版铺第 1 页。
- 退路：若现成封面满版比例/分辨率不佳，则重排干净标题页（书名 + 副标题 + 作者 + 版本 + 一张配图）。
- **版权页内容**：书名、作者（yeasy）、版本号（`v2.10.0`）、构建日期、授权声明（“已授权多家俱乐部/学校教学使用，未经授权禁止商用”）、GitBook 链接、PDF/HTML 下载入口。

## 9. 可重复性 / 使用

- `python tools/build_docx.py`（默认两种语言）或 `--lang cn|en`。
- 产物覆盖仓库根的两个 docx。
- 尽量不引入额外 Python 依赖（裁图用 sips、前置页用 docx skill 脚本 / XML 注入）。

## 10. 验证

- 构建后做 docx 校验（docx skill `validate.py`）。
- LibreOffice 渲染 PDF，逐项截图检查：封面、目录页码、首章另起页、图注、表格、页眉页脚、中英字体。
- 抽样核对：随机章节 docx 正文文本与 md 一致；docx 内图片数 == md 引用数。

## 11. 风险 / 待实现期验证

- pandoc 生成的 Word 目录页码需在 Word 首次打开时更新（Word 正常行为）。
- “每章另起页”依赖 `Heading1` 样式的 page-break-before，需在模板内设好。
- 封面满版与 16 开比例匹配，裁切点需按实际图像微调。
- 模板里的“宋体/黑体”需确认 LibreOffice 与 Word 都能正确映射；必要时回退到等价系统字体。
- 中文标点/断行 pandoc 一般无碍，但需渲染抽查确认。
