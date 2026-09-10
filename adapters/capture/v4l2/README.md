# V4L2 采集适配器

该模块实现通用 `rtctrl_capture_backend` 端口，封装 Linux 多平面 MMAP 采集。
原生结构、系统调用和颜色转换位于 `src/`；通用句柄与借用状态仍由采集核心管理。

应用装配入口：

```c
#include <rtctrl/adapters/v4l2/capture.h>

struct rtctrl_camera* camera = NULL;
struct rtctrl_v4l2_config config = {.device = "/dev/video31"};
int result = rtctrl_v4l2_open(&config, &camera);
```

调用方必须检查 result，并按通用接口的借用契约 acquire/release/close。
设备路径按实际板端拓扑设置。应用通过
`target_link_libraries(app PRIVATE rtctrl_vision_v4l2)` 获得创建接口的 include 路径。
业务消费者只链接 `rtctrl_capture`，不包含此适配器头文件。

`RTCTRL_ENABLE_V4L2=OFF` 时不创建此 target。默认安装只包含静态链接该适配器的
相机工具，不导出适配器库或创建头文件。原 `rtctrl/vision/v4l2_capture.h` 路径已移除。
内核及 SDK 不在本目录中修改。
