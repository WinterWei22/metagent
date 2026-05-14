# D2 — User actions required (off-session)

D1 docker build is running in background. D2(reference DB)有一步必须你手动做,因为涉及邮箱注册 + 下载凭证。

## Step 1: Register on metdna.zhulab.cn (5 min)

- 网址: https://metdna.zhulab.cn/
- 注册理由: GitHub 上的 MetDNA2 R 包不带 `zhuMetLib`,`zhuMetLib_orbitrap`,`zhuRPlib`,`lib_rt`,`lib_ccs`(版权限制)。Webserver 注册是官方提供这些 lib 的唯一渠道。
- License: free for **non-commercial** use(已对齐项目 scope)
- 联系邮箱(若注册有问题): metdna@sioc.ac.cn

**注册时建议:**
- 使用学术/项目邮箱(不要个人邮箱)
- 单位/项目栏写: "MetAgent benchmark spike — academic non-commercial feasibility study"
- 注册成功后,在 dashboard / download / library 区域找以下文件名:
  - `zhuMetLib*.RData` 或 `.rda`
  - `lib_rt.RData`
  - `lib_ccs.RData`
  - `zhuMetlib_orbitrap.RData`(若提供)
  - `zhuRPlib.RData`(若提供)

## Step 2: 把下载文件放到这里

```bash
# 假设你下载到 ~/Downloads/
mv ~/Downloads/zhuMetLib*.RData experiments/spike_tidymass/data/
mv ~/Downloads/lib_*.RData experiments/spike_tidymass/data/
ls -lh experiments/spike_tidymass/data/   # 给我看大小
```

我会在 D3 的 R script 里 `load()` 这些 RData 文件。

## Step 3: 我恢复后告诉我下面四件事

1. 注册流程是否顺畅?(有 yellow flag 要记到 D5 report)
2. Lib 下载总大小(M / G)
3. Lib 文件格式(RData / sqlite / csv)
4. 下载页面有没有提到 redistribution / commercial restrictions

---

## Fallback: 如果 webserver 注册失败 / lib 拿不到

我会改路径到:
- 选项 B:用 MoNA/MassBank 公开 spectra 做替换 lib(D2 多花 4-6h 写格式转换)
- 选项 C:直接写 no-go report(D5)

---

## Aside: MetDNA3 已经存在?

搜索过程中看到 "MetDNA3 webserver" 提法。如果你注册时发现实际是 MetDNA3 而非 MetDNA2,告诉我,可能要重新评估目标版本。
