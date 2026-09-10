# 机器人产品配置

products 保存具体机器人型号的接线、关节拓扑和标定数据；platforms 保存 SoC、
计算板及 BSP 配置。同一机器人产品可以使用不同计算板。

当前 yidong23 提供已审查的 23 关节、三 EtherCAT master 拓扑，目标为
`rtctrl_product_yidong23`。只有显式链接该 target 的源码树消费者可包含
`rtctrl/products/yidong23/topology.hpp`。现有 `rtctrl::profiles::yidong23`
命名空间和所有数值保持不变。产品数据不随通用模块 package 安装。

通用 MotorTopology 类型属于 modules/actuator；具体 kTopology 实例属于本目录。
`RTCTRL_PRODUCT` 仍选择 control-sim、vision-node 等运行组合，并不等于机器人型号。
humanoid23 preset 仍通过 RTCTRL_JOINT_COUNT=23 选择控制帧容量。
