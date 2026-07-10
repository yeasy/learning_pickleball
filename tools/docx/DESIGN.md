# DOCX 可重建流水线

## 目标

- 从 `cn/SUMMARY.md` 和 `en/SUMMARY.md` 的 28 个有序条目生成中、英文 Word 版。
- 不读取、不修补任何旧 DOCX；每次都从 Markdown、图片和样式构建器重建。
- 固定 185 x 260 mm 页面、正文与标题样式、Heading 1 章前分页、页眉页脚、双语静态目录、封面与本地图片。
- 构建中不下载远程图片；书内本地图片必须存在，否则明确失败。

## 实现

- `tools/build_docx.py`：解析 SUMMARY、按顺序合并 Markdown、规范化图片路径、调用 Pandoc，注入封面/版权页、物化 28 项目录并设置文档元数据。
- `tools/docx/build_reference_doc.py`：用 `python-docx` 从代码生成中、英文样式模板，不需要提交二进制 reference DOCX。
- `_images/cover.jpg`：构建时用 Pillow 按左/右半幅生成中/英文封面，不依赖已生成封面。
- `requirements-docx.txt`：锁定直接 Python 依赖；Pandoc 是唯一系统级构建依赖。

## 使用

```bash
python3 -m pip install -r requirements-docx.txt
python3 tools/build_docx.py
```

只生成某个语种，或改变输出目录：

```bash
python3 tools/build_docx.py --lang cn
python3 tools/build_docx.py --lang en --output-dir /tmp/learning-pickleball-docx
```

默认产物为仓库根目录的 `learning_pickleball-cn.docx` 和 `learning_pickleball-en.docx`；它们由 `/learning_pickleball-*.docx` 精确忽略，不会隐藏其他 DOCX 资料。

## 可重现性

- 条目和章节顺序只由对应 `SUMMARY.md` 决定。
- 样式模板、封面裁切和前置页都由受版本控制的代码生成。
- 文档核心时间使用 `SOURCE_DATE_EPOCH`；未设置时使用固定值，避免元数据随运行时间漂移。
- 输出先在临时目录完成，再原子替换目标；旧产物不会成为新产物的输入。

## 验证

```bash
python3 -m unittest -v tests.test_build_docx
```

测试仅使用 Python 标准库检查 OOXML ZIP：包结构、28 个 H1 的 SUMMARY 顺序、标题元数据、静态目录、字段更新设置、页面尺寸、Heading 1 分页和嵌入图片。交付前还应用 LibreOffice 导出 PDF，逐页检查封面、目录、表格、图片、中英文字体和分页。
