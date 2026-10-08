# 全双工契约基线与真实调用链红例

这是离线基线，生产驱动/公共补丁/guard/Image/旧冻结未修改；无板、网络或硬件START操作。可评审契约与最小分段见 [DESIGN.md](DESIGN.md)。主控已据真实红例授权另一个目录制作ASoC打开失败候选，本目录只保存原行为。

最新证据为 `model-v5/input-manifest.json` 与 `runs-v4/receipt.json`：23普通源/头/证据输入、57逐字实际函数；host、ASan+UBSan、静态AArch64 QEMU编译均exit0，执行均exit1，25项目标契约全部红、76项实际边界观察正确，运行stderr空。exit1是精确列名的业务red，不是编译错误/崩溃/硬件通过。CPU v12 SHA `7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141`；所有输入、函数、日志与ELF另按完整SHA封存。

## 复现的缺口

- 两open/单close（peer idle或running、两个方向）：simple-card先把codec请求清0，CPU合法拒绝清0且保留请求，出现非sticky诊断；真实deactivate/DAI活动数仍保留peer。
- 顺序第二START在CPU component阶段拒绝，平台DMA未GO；竞争双方component均通过并DMA GO后，CPU DAI只提交一个，C3只回滚失败方向prefix，成功peer继续运行。
- 打开失败串行rollback会多发sysclk0并清codec cache；失败startup在unlock→clean重新lock窗口遇到peer最后close时，真实单指针startup mark被清掉，failed CPU pointer残留，synthetic非NULL child clocks漏两引用。
- 真实PM get/put的单指针mark：full get后peer normal put或peer新get可使旧rollback漏每component一引用；partial get失败遇peerclose漏本次成功prefix。-EACCES和返回1均有usage引用，原串行首/中/末失败的当前member noidle与成功prefix auto-put分别一次，已实际观察。
- 人为started=3的反例：两方向STOP都因peer位返回EBUSY，平台DMA独立清理仍被尝试，共同XFER/CPU mask不闭合。该状态不是当前v12合法可达，只用于反驳“删START gate就完成全双工”。

## 版本与材料保留

`model-v3/runs-v2` 保留54函数/20 red/62观察，PM helper当时是显式理想化依赖模型，不覆盖真实mark_pm；其原manifest覆盖前已逐SHA保存。旧runner未及时快照，后按已知改动恢复，SHA与当时收据完全相等，放在 `baseline-v3-evidence/runner-recovered-exact.py`。旧prepare脚本未记录原SHA，无法把当前脚本冒充旧原版；该准备器历史材料缺口明确保留，不影响逐字源函数、已保存fixture/ELF/raw日志的检查。

`model-v4/runs-v3` 为57真实函数/24 red/68观察，增加真PM/symmetry helper；`baseline-v4-evidence` 在后续编辑前保存准备器/runner/fixture/manifest。旧model和输入未改。`model-v5/runs-v4` 仅增加前缀/正返回与peer-get PM边界；每个新model自带manifest和prepare快照，runner只读指定版本manifest，不再覆盖根旧文件。

Windows准备器长路径失败（未编译）保留 `prepare-failed-v1.json` 和 partial inputs/model-v1；`model-v2/runs-v1` 的三环境编译错误保留，涉及模型macro排版、日志参数消费和prepare调用参数纠正。以上失败从未记为业务red通过。

## 范围与下一步

真实部分包括CPU lifecycle、ASoC open/clean/trigger、DAI/link/component trigger dispatcher、runtime/DAI活动计数、PM wrapper、symmetry helper、simple startup/shutdown和codec sysclk setter。kernel PM调度/CCF/regmap/IRQ、ALSA constraint syscall边界、component open/module helper、codec trigger、平台DMA和实际PLL/DAPM是显式API模型或未覆盖；不宣称完整kernel ABI、PL330硬件、PM/remove安全或实机通过。

最小生产顺序是先持锁startup失败清理，加get本调用local-prefix回收及PCM/compressed get失败caller同步修改（避免double-put），再machine同DAI peer门。CPU zero gate不放松，PM回调/pinctrl仍锁外。RK817 voice共享cache与pinctrl sleep并发不在当前hifi/default-only保证内。后续同config、codec共享PLL、双START/单STOP、joint fault和两allocation隔离仍需分别审查；本基线不授予双向START。
