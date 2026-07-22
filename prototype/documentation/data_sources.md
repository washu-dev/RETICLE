# RETICLE Gene Explorer — 数据源说明

> 这个网站每搜一个基因，会发 **3 个请求**，分别打不同的数据源。本文说明
> **STRING / PubMed / NCBI / GO / BioGRID** 各自用在哪、出现在界面的哪一块、对应哪段代码。

代码位置：后端 `web/app.py` + `script/external_sources.py`；前端 `web/index.html`。

---

## 一张总表

| 数据源 | 提供什么 | 后端入口 | 界面上你看到的 |
|---|---|---|---|
| **BioGRID**（本地 DB） | 整个**定量报告**：fitness / stress / reporter 三条轴、percentile 分布、hit、cell line、context、verdict | `/api/gene` → `gene_payload()` | 基因名下方所有图表（双极轴、直方图、"where it matters most"、翻转提示） |
| **PubMed**（经 NCBI E-utilities） | ① 论文**数量** → darkness；② 论文**摘要** → RAG 证据 | `/api/context`（计数）<br>`/api/interpret`（摘要） | darkness 卡里的 "N papers"；AI reading 底部的 **PMID 引用链接** |
| **NCBI**（基因注解，经 MyGene.info） | 基因名 + **RefSeq 功能摘要** | `/api/context` → `gene_annotation()` | "Known to science" 那段说明文字 |
| **GO**（Gene Ontology，经 MyGene.info） | GO 注解**条数** → darkness 的另一半 | `/api/context` → `gene_annotation()` | darkness 卡里的 "N GO terms" + darkness 评分 |
| **STRING** | 已知**功能伙伴** | `/api/context` + `/api/interpret` | "Known to science" 里可点击的 partner chip；也喂给 AI |
| **WashU gpt-4o**（不是数据源，是合成器） | 把上面所有东西综合成一段解读 | `/api/interpret` → `interpret()` | "AI reading" 那段文字 |

> ⚠️ 澄清两点常见误解：
> 1. **PubMed 就是 NCBI 的一个数据库**——网站访问 PubMed 走的是 NCBI E-utilities（`esearch` / `efetch`）。所以"PubMed"和"NCBI"是同一套基础设施。
> 2. 表里那条 "NCBI 基因注解"（名字 + RefSeq 摘要）和 GO 条数，**实际是通过 MyGene.info 拿的**（它聚合了 NCBI/Entrez 的 RefSeq + GO），不是直接打 NCBI E-utilities。数据**来源**是 NCBI/GO，**取数通道**是 MyGene。

---

## 搜一个基因时，3 个请求各打了谁

```
用户搜 "C1orf109"
│
├─ 1. GET /api/gene?symbol=C1orf109          ── 只用 BioGRID（本地，秒回）
│      gene_payload(): 查 harmonized_scores + screen_metadata + screen_metadata_curated
│      → fitness/stress/reporter 三块 + verdict
│      → 渲染：基因名、双极轴、直方图、context 列、翻转提示
│
├─ 2. GET /api/context?symbol=C1orf109       ── MyGene + NCBI(PubMed) + STRING（带缓存）
│      ex.enrich():
│        · gene_annotation()  → MyGene：名字 + RefSeq summary + GO 条数
│        · darkness()         → pubmed_count()[NCBI esearch] + GO 条数 → 0–10 分
│        · string_partners()  → STRING：已知伙伴
│      → 渲染："Known to science + darkness" 那一条带
│
└─ 3. POST /api/interpret                      ── 复用上面的 enrich + 拉 PubMed 摘要 + gpt-4o
       interpret():
         · ex.enrich()                         → darkness/summary/partners（缓存命中，不重复打网）
         · pubmed_abstracts(pubmed_pmids())    → NCBI efetch：top-5 相关论文摘要（= RAG 检索）
         · WashU gpt-4o                        → 把 BioGRID 信号 + darkness + STRING + 摘要 合成
       → 渲染："AI reading" 文字 + PMID 引用链接
```

---

## 逐源详解

### 1. BioGRID —— 网站的定量核心
- **是什么**：你自己 pipeline 产出的本地 SQLite (`processed_data/reticle_master.db`)：`harmonized_scores`（28.2M 行）+ `screen_metadata` + `screen_metadata_curated`（含 `assay_domain`）。
- **用在哪**：`/api/gene` 的 `gene_payload()`。它是**唯一离线、秒回**的源。
- **界面**：基因名、verdict、fitness/stress 两块（双极轴 + 4 个统计卡 + 直方图 + "where it matters most"）、reporter 计数、翻转提示——**全部来自 BioGRID**。
- **不需要网络/key**。

### 2. PubMed（经 NCBI E-utilities）—— 两处用途
- **论文计数**：`pubmed_count()` 用 `esearch`（`{gene}[gene] AND human[orgn]`）拿总数。→ **darkness 评分**的主成分 + darkness 卡里的 "N papers"。
- **论文摘要**：`pubmed_abstracts(pubmed_pmids())` 用 `esearch`(按相关性取 top-5 PMID) + `efetch`(取摘要)。→ 喂给 gpt-4o 当 **RAG 证据**，AI reading 底部列出这些 PMID 作为引用。
- **key**：`.env` 里的 `NCBI_API_KEY`（你已设）→ 10 请求/秒（否则 3/秒）。

### 3. NCBI 基因注解（经 MyGene.info）
- **是什么**：`gene_annotation()` 打 MyGene.info，拿 `entrezgene` + `name` + **RefSeq summary** + GO terms。
- **界面**："Known to science" 那段功能描述文字（暗基因没有 summary 时显示"Poorly characterized…"）。
- **无需 key**。

### 4. GO（Gene Ontology，经 MyGene.info）
- **是什么**：上面同一个 MyGene 调用里的 GO 条数（BP+MF+CC）= `go_total`。
- **用在哪**：**darkness 评分的另一半**（注解越少越暗）+ darkness 卡里的 "N GO terms"。
- **无需 key**。

### 5. STRING —— 已知功能伙伴
- **是什么**：`string_partners()` 打 STRING API，拿 top 互作/功能伙伴。
- **界面**："Known to science" 里那排可点击的 partner chip（点一下就 explore 那个基因）。
- **也喂给 AI**：interpret 的 prompt 里有 "KNOWN PARTNERS (STRING)"，让模型判断"暗基因是否和已知伙伴行为一致 → 脱孤候选"。
- **无需 key**。

### 6. WashU gpt-4o —— 合成器（不是数据源）
- 把 BioGRID 信号 + darkness + STRING + PubMed 摘要综合成一段解读，要求**引用 PMID**、不编造。
- 走 `script/llm_client.py`（WashU gateway），**需连 WashU VPN**。

---

## darkness 评分用了哪些源
darkness = `10 × (0.6·dark_pub + 0.4·dark_go)`
- `dark_pub` ← **PubMed 论文数**（NCBI esearch）
- `dark_go`  ← **GO 注解条数**（MyGene/GO）

即 **darkness = PubMed + GO 两个源的组合**。BioGRID 和 STRING 不参与 darkness 计算。

---

## 缓存与离线行为
- 所有外部源（NCBI/MyGene/STRING）结果缓存在 `processed_data/external_cache.db`（30 天 TTL），第二次查同一基因**秒回、不再打网**。
- **离线/无 VPN 时**：`/api/gene`（BioGRID）照常工作；`/api/context` 取决于公网（NCBI/MyGene/STRING 是公网，通常可达）；`/api/interpret` 的 gpt-4o 需要 WashU VPN，否则优雅报错提示连 VPN。
- 外部源全部 **fail-soft**：某个源挂了返回空/None，不会让页面崩溃。
