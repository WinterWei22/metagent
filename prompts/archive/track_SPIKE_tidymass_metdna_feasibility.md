# Track SPIKE — TidyMass / metdna Deployment Feasibility

**Session ID:** `track_SPIKE_tidymass_metdna_feasibility`
**Branch:** `feature/spike-tidymass` (新建,base on `feature/sub6-v2-integrated`)
**Estimated work:** 1-2 days
**Type:** Feasibility spike — **NOT** integration. Output is a go/no-go report.

---

## Why this matters

我们考虑集成 TidyMass 生态(尤其 `metdna` package)解决两个痛点:
1. Sub-6A 鉴定上限受 library_search 单源限制(67% top-1)
2. Dark metabolite(未被 library 收录的 m/z)无法贡献 pathway 分析

`metdna` 用网络传播算法把 confident identification 的标注扩展到周边 unidentified feature,理论上能把识别率拉到 80%+。

**但** TidyMass 是 R 生态,有 R-Python interop / docker / 依赖管理 / DB 准备 4 个未知风险。本 spike 的任务是**用最小代价摸清这 4 个风险**,产出 go/no-go 决策依据。

**Hard rule:** 本 session **不**做生产集成,**不**改任何现有代码,**不**碰 verifier / orchestrator / Sub-6 数据。所有产物落在 `experiments/spike_tidymass/` 隔离目录下。

---

## Hard scope boundaries

**You MAY:**
- 创建 `experiments/spike_tidymass/` 目录,所有 spike 产物落这里
- 安装 R / TidyMass / metdna(在 docker 或临时 conda env 内,不污染主 env)
- 下载 metdna 必需的 reference DB(到 `experiments/spike_tidymass/data/` 或临时 cache)
- 写 1-2 个测试 R 脚本 + Python wrapper
- 跑 ≤5 条真实 spectrum(从 Sub-6A v2 抽样)做 smoke test
- 写 spike report 到 `reports/spike/tidymass_feasibility_2026-05-XX.md`

**You MAY NOT:**
- 修 `tools/` / `verifier/` / `evaluation/` / `orchestrator/` 任何文件
- 改 main repo 的 `requirements.txt` / `environment.yml`
- 跑全量 Sub-6A 38 task(spike 只测可行性,不算指标)
- 写正式 docker compose 或 production deployment 配置

---

## Background reading (mandatory first action)

1. https://www.tidymass.org/ — 官网,看 ecosystem 全景
2. `metdna` GitHub: https://github.com/tidymass/metdna 或 https://github.com/jaspershen/MetDNA2
3. `metid` GitHub: https://github.com/tidymass/metid (作为对比,理解 TidyMass 架构)
4. metdna 论文: Shen X et al, Nat Commun 2019 (MetDNA1) + Nat Methods 2024 (MetDNA2 if 已发表)
5. 现有 docker shim 范式: `tools/cfm_id/` 目录(看怎么 wrap 一个外部工具用 HTTP/JSON)
6. 现有 spectrum schema: `schemas/__init__.py` 的 `Spectrum` class
7. Sub-6A 抽样数据: `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl` 第一条 task

In your first response,确认:
- metdna 当前 GitHub 状态(active maintenance? 最后 commit 时间? open issues 数量?)
- metdna 是 MetDNA1 还是 MetDNA2,版本/算法差别
- 哺乳动物代谢 (human/mouse) 是否 first-class supported(很多 TidyMass 例子是植物)
- Reference DB 大小(MS2 lib + reaction network)
- 大致依赖清单(BiocManager 包数量)

不要写代码直到我 confirm。

---

## Deliverables (4 个 risk axis)

### D1 — Risk 1: 部署可行性(2-4 小时)

测试能否在 docker 里把 metdna 跑起来。

**做法:**
```bash
mkdir -p experiments/spike_tidymass
cd experiments/spike_tidymass
# 写 Dockerfile.spike,基础 image: rocker/r-bioc:latest 或 bioconductor 官方
# 装 BiocManager + tidymass + metdna
# Build image,记录:
#   - build wall time
#   - final image size (GB)
#   - 失败的 dependency(若有)
```

**Acceptance:**
- ✅ Docker image build 成功(≤2 hr build, ≤5 GB image)
- ⚠️ Build 成功但 image >10 GB → 标 yellow flag
- ❌ Build 反复失败 → 直接 escalate,不继续 D2-D4

**输出:** `experiments/spike_tidymass/Dockerfile.spike` + build log

### D2 — Risk 2: Reference DB 准备(1-2 小时)

metdna 需要的 reference data:
- MS2 reference library(MassBank-style,几百 MB 量级)
- Metabolic reaction network(KEGG-derived,~500 MB)
- Mammalian / human pathway 注释

**做法:**
```bash
# 在 docker 内或外,跑 metdna 的 demo data 下载脚本
# (具体命令:`metdna::download_demo_data()` 或类似)
# 记录:
#   - 总下载体积 (GB)
#   - 下载时长
#   - 数据格式(R rds vs sqlite vs csv)
#   - 是否需要外部账号(MoNA/MassBank licenses)
```

**Acceptance:**
- ✅ 全部 reference DB 公开免费 + ≤10 GB,下载 ≤30 分钟
- ⚠️ 需要 license 但学术免费 → 标 yellow,继续
- ❌ 必需 commercial license / >50 GB → escalate

**输出:** `experiments/spike_tidymass/data/MANIFEST.md`(列出每个 DB 大小、来源、license)

### D3 — Risk 3: API / I/O 可调用性(2-4 小时)

测试我们能否从 Python 调 metdna 拿到结构化输出。

**做法:**
```bash
# 写一个 minimal R script: experiments/spike_tidymass/run_metdna.R
# 输入: JSON file (1 条 Spectrum,from Sub-6A v2 task #0 第一条)
# 输出: JSON file,结构应该至少包含:
#   - top-k identified compounds(name + InChIKey + KEGG ID + score)
#   - network-propagated annotations(从 confident hit 扩展出的额外 IDs)
#   - 用了哪些 reference DB(provenance)

# 写一个 Python wrapper: experiments/spike_tidymass/metdna_shim.py
# 用 subprocess 调 docker run + Rscript
# JSON I/O 接口必须干净(无 R 输出文本污染)
```

**Acceptance:**
- ✅ 能从 Python 输入 1 条 Spectrum → 拿到结构化 JSON 结果
- ⚠️ 能跑通但要手工解析 R 输出 → 标 yellow
- ❌ R 接口不允许干净 JSON I/O / 必须用 RData 格式 → escalate(意味着需要写复杂 adapter)

**输出:** `run_metdna.R` + `metdna_shim.py` + 一条真实 spectrum 的 JSON 输出样例

### D4 — Risk 4: Smoke test on 5 spectra(2 小时)

跑 5 条 Sub-6A v2 spectra 看实际行为。

**做法:**
```python
# 用 metdna_shim 跑 5 条 spectrum
# 抽样:Sub-6A v2 task #0 的前 5 条 differential_spectra
# 记录每条:
#   - wall time
#   - top-1 identified compound vs ground truth (correct?)
#   - 是否触发 network propagation(找到 unidentified neighbors)
#   - 输出大小
# 跟现有 library_search 在同 5 spectra 的结果对比
```

**Acceptance:**
- ✅ 5 条全跑通,网络传播至少 1 条产生额外 annotation
- ⚠️ 5 条跑通但都没触发 network 传播 → 标 yellow(可能 mammalian network 太稀疏)
- ❌ 多条 fail / 网络传播完全不工作 → escalate

**输出:** `experiments/spike_tidymass/smoke_test_results.json` + 跟 library_search 的对比表

### D5 — Spike Report

`reports/spike/tidymass_feasibility_2026-05-XX.md`,包含:

#### 1. Executive summary (3 行)
- 4 个 risk axis 各打分(✅ / ⚠️ / ❌)
- Go / no-go / conditional-go 决策
- 如果 go,推荐集成方案(docker shim / 直接 conda / R 嵌入)

#### 2. Risk 1: 部署
| metric | value |
|---|---|
| Docker image size | ? GB |
| Build time | ? min |
| 失败的依赖(若有) | ? |
| 装机方式 | docker / conda / both work |

#### 3. Risk 2: Reference DB
| DB | size | source | license | 下载时长 |
|---|---|---|---|---|
| MS2 library | ? | ? | ? | ? |
| Reaction network | ? | ? | ? | ? |

#### 4. Risk 3: API / I/O
- 调用方式(subprocess / HTTP / direct R library)
- 输入 schema 转换复杂度
- 输出 schema 干净度
- 1 条 spectrum 端到端 wall time

#### 5. Risk 4: Smoke results
| spectrum_id | metdna top-1 | library_search top-1 | GT | metdna correct? | 网络传播 IDs |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... |

#### 6. Cost estimate(如果 go)
- 完整集成工程量(天)
- Docker production deploy 工作量
- 维护成本(R 环境 drift / DB 更新频率)
- 跑全 Sub-6A 38 task 的预期 wall time

#### 7. Recommendation
基于 4 个 risk axis 给最终决策:
- **Go**: 4 axis 全 ✅ → 直接进入正式 metdna 集成 session
- **Conditional-go**: 有 ⚠️ → 写明哪些条件需先满足
- **No-go**: 有 ❌ → 给替代方案(只用 metpath / ChemRICH / 或全跳过)

#### 8. Provenance + 时间花费

---

## Pitfalls

1. **R 包装 docker 第一次 build 慢得难以想象**(2 小时是底线,可能 4 小时)。设个长 timeout,别在 1 小时就放弃。

2. **TidyMass / metdna 的 R 依赖经常 broken**——尤其 BiocManager 跟 CRAN 版本不兼容。如果 build 失败,先 pin 一个老一点的 R version (4.3 而非 latest 4.4)。

3. **metdna 的 reaction network 默认是 KEGG human/mouse,不是植物**——这跟你 Sub-6A 哺乳动物 scope 匹配。但确认一下。

4. **不要尝试用 rpy2 嵌入** —— 跟主 conda env 冲突几率很高,subprocess 模式更稳。

5. **不要装到 main env**——会污染所有现有 verifier / sub6 测试。所有 R / TidyMass 必须在隔离 docker 或 throwaway conda env(`/tmp` 或 `experiments/spike_tidymass/.env`)。

6. **如果 D1 build 真的过不去**,不要硬撑修 dependency 一整天——直接写 escalation report,标 ❌,我们换 metpath only(更轻量)的方案。

7. **MoNA / MassBank reference 可能需要邮箱注册**——记下来,但**不要**用任何个人/工作邮箱注册,先写进 report 让我决定。

---

## Time budget

- D1 部署: 2-4h(主要是 docker build wait)
- D2 数据: 1-2h
- D3 API: 2-4h
- D4 smoke: 2h
- D5 report: 1h

**Total budget: 1-2 days**(含 docker build 等待时间)。

如果 D1 失败 → 直接跳 D5 写 no-go report,**不**继续 D2-D4。
如果 D1+D2 通但 D3 失败 → 写 conditional-go report(metpath 路线可行,metdna 路线被 R API 阻塞)。

---

## First action checklist

第一回合:
1. 读 7 个 background 文件(尤其确认 metdna 是 GitHub active 还是 stale)
2. 报告 metdna 当前版本(1 vs 2)+ 最近 commit + open issue 数
3. 报告 reference DB 总大小估计
4. 报告 mammalian / human 是否 first-class supported(看 demo)
5. 报告推荐 docker base image(rocker/r-bioc 哪个 tag)
6. 任何 clarifying question

不要装任何东西,不要 build docker,直到我 confirm 这 6 项。
