# Buildroot 服务启停

service-control.py 显式管理本工具启动的单个 companion 实例。不会修改网络、视觉服务，
不会安装启动项。S95rtctrl-companion.example 仅为可选 SysV 模板，默认不复制到 /etc/init.d。

环境文件使用字面 KEY=VALUE，每行一项，不支持 export、引号剥离、变量展开或 shell 命令。
文件应归运行服务的用户所有，权限 0600。示例（真实 token 自行填写，勿提交）：

    RTCTRL_VOICE_TOKEN=...
    ALSA_CONFIG_PATH=/userdata/rtctrl-companion/deploy/companion/asound-rv1126b.conf

手动启动：

    python3 -B /userdata/rtctrl-companion/deploy/companion/service-control.py start \
      --bundle /userdata/rtctrl-companion \
      --config /userdata/rtctrl-companion/config/companion/rv1126b.json \
      --env-file /userdata/rtctrl-companion/service.env \
      --state-dir /run/rtctrl-companion

停止或查询仅需指定相同 state-dir：

    python3 -B /userdata/rtctrl-companion/deploy/companion/service-control.py status --state-dir /run/rtctrl-companion
    python3 -B /userdata/rtctrl-companion/deploy/companion/service-control.py stop --state-dir /run/rtctrl-companion

restart 与 start 使用同样参数。status 运行时返回 0，否则返回 3；操作失败返回 1。
start 的成功只证明进程已启动并短时存活，HTTP 状态、后端、声卡仍需单独验收。
不会自动重启故障实例，不会停止旧 nohup 实例；首次迁移应明确停止已经确认属于本应用的旧实例。

监督器与应用拥有独立进程组，PID 文件同时记录 /proc 启动时间和随机监督器实例标记；
操作用 flock 串行化，陈旧 PID 不会用于杀死不匹配的进程。停止先 TERM，
应用最多获约 7 秒退出时间，随后仅对本实例进程组 KILL；控制命令的兜底也有时间界限。
不要在实例运行期间删除 state-dir 或手动改 PID 文件。

state-dir 必须归当前用户所有且权限 0700。默认放 /run，重启后自然清除。
service.log 加两个轮转文件，总大小约 192 KiB；超过 8 KiB 的单行丢弃。
环境文件中的值及常见 token/password/secret 环境值会从子进程日志中替换，
环境文件内容不会出现在启动 argv。不要把凭据写进配置路径、手动参数或应用自定义日志。

可选开机启用需要用户明确选择之后，才根据实际 Buildroot init 体系安装模板、
设定 ROOT/CONFIG/ENV_FILE/STATE 路径；本工具和打包脚本均不会自动执行此步骤。
