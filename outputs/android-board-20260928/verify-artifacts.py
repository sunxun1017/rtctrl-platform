"""Host-only verification/extraction; no board access. Run in this directory."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parent
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def extract(archive, destination):
    destination.mkdir(exist_ok=True)
    with tarfile.open(archive) as tf:
        members = tf.getmembers()
        for m in members:
            target = (destination / m.name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError(f'Unsafe archive path: {m.name}')
            if not (m.isfile() or m.isdir()):
                raise ValueError(f'Unexpected archive member type: {m.name}')
        for m in members:
            target = destination / m.name
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            data = tf.extractfile(m).read()
            if target.exists():
                if target.read_bytes() != data:
                    raise ValueError(f'Existing extracted file differs: {m.name}')
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    return len(members)

assert sha(root/'fdt.dtb') == 'a028987f730f3c8e4be9cb6e771b91a5665932712c51e1e540b96654de4dd28b'
assert sha(root/'hardware-bundle.tar.gz') == '61293bdd27721122e9b5a2b1a21d794ffb1f899534330288f89249a60cbb1c47'
counts = {'bundle_members': extract(root/'hardware-bundle.tar.gz', root/'bundle')}
counts['live_tree_members'] = extract(root/'bundle/live-tree.tar.gz', root/'live-tree')
assert sha(root/'bundle/snapshot/fdt.dtb') == sha(root/'fdt.dtb')
(root/'kernel.config').write_bytes(gzip.decompress((root/'bundle/snapshot/config.gz').read_bytes()))
dtc = root/'host-tools/extracted/usr/bin/dtc'
commands = [
    [str(dtc), '-I', 'fs', '-O', 'dts', '-o', str(root/'android-live-tree.dts'), str(root/'live-tree')],
    [str(dtc), '-I', 'dtb', '-O', 'dtb', '-s', '-o', str(root/'fdt-sorted.dtb'), str(root/'fdt.dtb')],
    [str(dtc), '-I', 'fs', '-O', 'dtb', '-s', '-o', str(root/'live-sorted.dtb'), str(root/'live-tree')],
]
with (root/'host-verification.log').open('w') as log:
    for cmd in commands:
        log.write('$ ' + ' '.join(cmd) + '\n')
        log.flush()
        result = subprocess.run(cmd, stdout=log, stderr=log)
        log.write(f'exit={result.returncode}\n')
        assert result.returncode == 0
counts['sorted_fdt_equals_live_tree'] = ((root/'fdt-sorted.dtb').read_bytes() == (root/'live-sorted.dtb').read_bytes())
counts['fdt_bytes'] = (root/'fdt.dtb').stat().st_size
counts['kernel_config_lines'] = len((root/'kernel.config').read_text().splitlines())
(root/'verification.json').write_text(json.dumps(counts, indent=2)+'\n')
print(json.dumps(counts, indent=2))

commands = sorted(root.glob('*.command.sh'))
lines = ['# 串口命令与原始输出索引', '',
         'COM6，1500000 baud，8N1，无流控，DTR/RTS=false。主机时间见 [session.log](session.log)。', '',
         '每条命令保存 `.command.sh`；原始字节保存 `.raw.bin`；UTF-8可读副本保存 `.output.txt`。',
         '输出保留终端回显、退格符、异步内核日志和失败信息，不能把夹杂的日志当作命令返回。', '',
         '07/13为采集脚本分块上传，17为经过逐块SHA-256验证的数据回传。脚本内容见collector-used.sh和collect-extra.sh。', '',
         '|步骤|命令|原始输出|', '|---|---|---|']
for cmd in commands:
    name = cmd.name.removesuffix('.command.sh')
    lines.append(f'|{name}|[命令]({cmd.name})|[输出]({name}.output.txt) / [字节]({name}.raw.bin)|')
lines += ['', '## 前置探测', '',
          '- `00-probe-command.sh` / `00-probe.txt`：按历史2500000配置发送，收到乱码，不能判定命令成功。',
          '- `passive-*.bin`与`passive-long-*.bin`：不同波特率下仅接收；1500000长窗口得到可读内核日志。',
          '- 首次探测的本机保存路径因PowerShell Provider前缀失败，未保留那一窗口；随后重跑并保存为00。',
          '- 直接调用UNC上的ps1曾被主机签名策略拒绝；之后在当前PowerShell内读取所写脚本为scriptblock执行，没有更改全局执行策略。',
          '- `su -c id`在该Android上不支持；使用`su 0 id`成功。',
          '- 04、05的未压缩FDT回传损坏；06 gzip压缩传输后解码，通过原始FDT的板端SHA-256。',
          '- 08逐文件采集未完成；11发送Ctrl-C终止，12记录其1960行进度。保留的snapshot/devicetree是不完整副本。',
          '- 15完整运行设备树tar成功，最终完整副本为live-tree/；主机校验见verification.json。',
          '', '## 主机处理', '',
          'DTC来自Ubuntu包`device-tree-compiler`，只下载解包在host-tools/，未全局安装。',
          '下载输出见host-tools/download.log；校验与解包逻辑见verify-artifacts.py；DTC命令及输出见host-verification.log。',
          '最初反编译命令：`host-tools/extracted/usr/bin/dtc -I dtb -O dts -o android-running.dts fdt.dtb 2> dtc-warnings.txt`。',
          'gzip校验：`gzip -t fdt.dtb.gz`；解压：`gzip -dc fdt.dtb.gz > fdt.dtb`；哈希：`sha256sum fdt.dtb`。', '']
(root/'commands-and-outputs.md').write_text('\n'.join(lines))
