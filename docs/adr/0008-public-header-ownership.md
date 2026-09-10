# ADR-0008：公开头文件边界与机器人产品配置

状态：Accepted，2026-09-10。补充 ADR-0007。

集中式 include 已迁入模块，但具体机器人数据仍随 actuator 导出，分帧命令源放在
transport 却依赖 bridge，runtime 端口 target 则暴露了缺少引擎依赖的头文件。

## 决策

- Yidong 拓扑移到 products/yidong23，通过 rtctrl_product_yidong23 显式提供。
  原拓扑回归测试随产品迁移。通用模块不依赖产品；产品头文件和 target 不安装。
- FramedCommandSource、FramedSourcePolicy、FramedSourceMetrics 归 rtctrl::bridge，
  头文件改为 rtctrl/bridge/framed_command_source.hpp，rtctrl_source_framed 目标名保留。
  它只需要 codec 接口，具体 FixedTargetCodec 由应用显式链接 rtctrl_protocol_target。
- runtime/ports/include 由 rtctrl_runtime_api 导出（包括共享 LoopMetrics 数据），
  timer/include 由 rtctrl_timer 导出，runtime/include 由 rtctrl_runtime 导出。
  代码内 rtctrl/runtime/... 拼写保持不变。
  安装头文件分别位于 rtctrl-modules/runtime/{ports,timer,engine}。
- 每个公开头文件根目录登记所属 target，统一用于安装和独立编译验证。
  C 头文件同时检查 C/C++，源码树和干净安装包使用同一份检查清单。
  可见性检查防止端口重新暴露引擎、底层 transport 暴露 bridge、actuator 暴露产品。
- 保留根 include/uapi：它是内核与用户态共享契约，不归单一模块私有。

其他模块继续使用简单的 include/src 布局，不为目录对称拆分更多 target。
*_api 提供公开声明及其头文件依赖；使用非内联实现仍须链接对应库。
关节数、标定参数、协议数值、控制行为与 UAPI 布局均不改变。

## 消费者迁移

旧 rtctrl/profiles/yidong23_topology.hpp 改为 rtctrl/products/yidong23/topology.hpp，
源码消费者显式链接 rtctrl_product_yidong23。既有 rtctrl::profiles::yidong23 命名空间保留。
FramedCommandSource 的 include 和命名空间迁到 bridge；不再通过命令源库隐式得到
FixedTargetCodec 的实现。安装验证继续使用干净目录，避免旧头文件掩盖边界错误。
