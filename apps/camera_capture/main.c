#include <err.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <stdbool.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define handle_error(msg)                                                           \
    do {                                                                            \
        perror(msg);                                                                \
        exit(EXIT_FAILURE);                                                         \
    } while (0)

/**
 * @brief
 *
 * @return int
 */
// static bool has_cap(const struct v4l2_capability* cap, __u32 bit) {
//     //
//     __u32 caps = (cap->capabilities & V4L2_CAP_DEVICE_CAPS);
//     // ? cap->device_caps
//     // : cap->capabilities;
//     // if (caps)// 如果是新驱动
//     caps = cap->capabilities; // 我要的就是整个设备的能力
//     if (!caps)
//         warnx("Using legacy capability query, we need to update the driver, we
//         need entry device
//         "
//               "capabilities");
//     return (caps & bit) != 0;
// }

int main() {
    const char* device_path = "/dev/video31";
    const int cap_frame_num = 300;

    // TODO: identify the device
    // int fd = open(device_path, O_RDONLY);// 摄像头要设置读写模式, 也要防止堵塞
    int fd = open(device_path, O_RDWR | O_NONBLOCK);
    if (-1 == fd) {
        perror("Failed to open camera device");
        return -1;
    }

    // struct v4l2_capability cap;
    // if (ioctl(fd, VIDIOC_QUERYCAP, &cap) == -1) {
    //     perror("Failed to query camera capability");
    //     close(fd);
    //     return -1;
    // }

    // printf("Camera capability:\n");
    // printf("  Driver: %s\n", cap.driver);
    // printf("  Card: %s\n", cap.card);
    // printf("  Bus info: %s\n", cap.bus_info);
    // printf("  Version: %08X\n", cap.version);
    // // printf("  Capabilities: %08X\n", cap.capabilities);

    // bool is_capture = has_cap(&cap, V4L2_CAP_VIDEO_CAPTURE);
    // bool is_capture_mp = has_cap(&cap, V4L2_CAP_VIDEO_CAPTURE_MPLANE);
    // bool has_streaming = has_cap(&cap, V4L2_CAP_STREAMING);
    // bool has_readwrite = has_cap(&cap, V4L2_CAP_READWRITE);

    // printf("Video capture      : %s\n", is_capture ? "yes" : "no");
    // printf("Capture (multiplanar): %s\n", is_capture_mp ? "yes" : "no");
    // printf("Streaming I/O      : %s\n", has_streaming ? "yes" : "no");
    // printf("read/write I/O     : %s\n", has_readwrite ? "yes" : "no");

    // char *addr;
    // struct stat sb;
    // size_t length;
    // off_t offset, pa_offset;
    // pa_offset = offset & ~(sysconf(_SC_PAGE_SIZE) - 1);
    // /* offset for mmap() must be page aligned */
    // addr = mmap(NULL, length + offset - pa_offset, PROT_READ,
    //                    MAP_PRIVATE, fd, pa_offset);
    // if (addr == MAP_FAILED)
    //     handle_error("mmap");
    // 不要自己手动mmap了

    // 1. 设置格式
    struct v4l2_format fmt = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
                              .fmt.pix_mp = {.width = 2112,
                                             .height = 1568,
                                             .pixelformat = V4L2_PIX_FMT_NV12,
                                             .num_planes = 1}};
    int ret = ioctl(fd, VIDIOC_S_FMT, &fmt); // 设置格式
    if (ret == -1) {
        perror("Failed to set format");
        close(fd);
        return -1;
    }
    // S_FMT 后你要回读，驱动可能会调整它
    __u8 num_planes = fmt.fmt.pix_mp.num_planes;

    // 2. 申请 buffer
    struct v4l2_requestbuffers req = {
        .count = 4,                                 // TODO: 这个是依据什么呢
        .type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, // 多平面采集，必须和 S_FMT 时的
                                                    // type 一致
        .memory = V4L2_MEMORY_MMAP,                 // 使用 mmap 方式
    };
    ret = ioctl(fd, VIDIOC_REQBUFS, &req); // 这就是在申请buf
    if (ret == -1) {
        perror("Failed to request buffers");
        close(fd);
        return -1;
    }
    __u32 buf_count = req.count;

    // 3. 映射每个 buffer  的每个 plane，一个 buffer 就是一帧
    void* maps[buf_count][num_planes];
    // 每个 buffer
    // 都有一个，放到循环内和外，没有任何差异，因为这是数组，编译器会优化掉的
    struct v4l2_plane planes[num_planes];
    for (__u32 i = 0; i < buf_count; i++) {
        // 然后又把这个平面放进 buffer 里面
        struct v4l2_buffer buf = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
                                  .index = i,         // buffer 的索引
                                  .m.planes = planes, // 平面的地址
                                  .length = num_planes,
                                  .memory = V4L2_MEMORY_MMAP};
        // ret = ioctl(fd, VIDIOC_QBUF, &buf); // 这个是转交所有权，把这个buf交给驱动
        // if (ret == -1) {
        //     perror("Failed to queue buffer");
        //     close(fd);
        //     return -1;
        // }
        // 这是完全不对的，你都要mmap了，就不要 交出所有权啊！！！
        for (__u8 j = 0; j < num_planes; j++) {
            maps[i][j] = mmap(NULL,
                              planes[j].length, // 每个平面都要映射
                              PROT_READ | PROT_WRITE,
                              MAP_SHARED,
                              fd,
                              planes[j].m.mem_offset); // 不应该使用private
        }
    }
    // 4. 入队所有 buffer，你映射完了，就要放进去了
    for (__u32 i = 0; i < buf_count; i++) {
        struct v4l2_buffer buf = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
                                  .index = i,         // buffer 的索引
                                  .m.planes = planes, // 平面的地址
                                  .length = num_planes};
        ret = ioctl(fd, VIDIOC_QBUF, &buf); // 一直在申请，放进 buf
        if (ret == -1) {
            perror("Failed to queue buffer");
            close(fd);
            return -1;
        }
    }
    // 5. 启动采集
    enum v4l2_buf_type type =
        V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE; // 要和前面申请 buf 和映射
                                            // buf的时候对应上
    ret = ioctl(fd, VIDIOC_STREAMON, &type);
    if (ret == -1) {
        perror("Failed to start streaming");
        close(fd);
        return -1;
    }

    // 6. 采集循环
    while (1) {
        struct v4l2_plane planes[num_planes];
        struct v4l2_buffer buf = {
            .type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
            .memory = V4L2_MEMORY_MMAP,
            .length = num_planes,
            .m.planes = planes,
        };
        ioctl(fd, VIDIOC_DQBUF, &buf); // 驱动写好了，把他交给我

        int idx = buf.index;
        // 处理数据：maps[idx][0] 是 Y plane，maps[idx][1] 是 UV plane
        // 各 plane 的有效数据长度：planes[j].bytesused
        // 各 plane 的每行字节数：fmt.fmt.pix_mp.plane_fmt[j].bytesperline

        ioctl(fd, VIDIOC_QBUF, &buf); // 重新入队
    }

    close(fd);
    return 0;
}
