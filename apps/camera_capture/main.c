#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <sys/select.h>

#define REQUEST_BUFFER_COUNT 4
#define CLEAR(x) memset(&(x), 0, sizeof(x))
#define fwidth 2112
#define fheight 1568
struct buffer {
    void* start[VIDEO_MAX_PLANES];
    size_t length[VIDEO_MAX_PLANES];
};
static const char* dev_name;
static int fd = -1;
struct buffer* buffers;
static unsigned int n_buffers;
static unsigned int n_planes;
static int out_buf;
static int force_format = 1;
static const unsigned int frame_count = 70;

static void errno_exit(const char* s) {
    fprintf(stderr, "%s error %d, %s\n", s, errno, strerror(errno));
    exit(EXIT_FAILURE);
}

void open_device(void) {
    /* -----------------------identify path exist------------------------------- */
    struct stat sb;
    CLEAR(sb);
    if (-1 == stat(dev_name, &sb)) {
        fprintf(stderr, "Device not found: %s\n", dev_name);
        exit(EXIT_FAILURE);
    }
    /* -----------------------identify device exist----------------------------- */
    if (!S_ISCHR(sb.st_mode)) {
        fprintf(stderr, "Device is not a character device: %s\n", dev_name);
        exit(EXIT_FAILURE);
    }
    fd = open(dev_name, O_RDWR | O_NONBLOCK);
    if (-1 == fd) {
        fprintf(stderr, "Failed to open camera device: %s\n", dev_name);
        exit(EXIT_FAILURE);
    }
}

/**
 * @brief loop ioctl until do not interrupt
 */
static int xioctl(int fd, unsigned long int request, void* arg) {
    int r;
    do {
        r = ioctl(fd, request, arg);
    } while (-1 == r && EINTR == errno);
    return r; /* not interrupt */
}

static void init_mmap(void) {
    struct v4l2_requestbuffers req;

    CLEAR(req);

    req.count = REQUEST_BUFFER_COUNT;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    req.memory = V4L2_MEMORY_MMAP;

    if (-1 == xioctl(fd, VIDIOC_REQBUFS, &req)) {
        if (EINVAL == errno) {
            fprintf(stderr,
                    "%s does not support "
                    "memory mapping\n",
                    dev_name);
            exit(EXIT_FAILURE);
        } else {
            errno_exit("VIDIOC_REQBUFS");
        }
    }

    if (req.count < 2) {
        fprintf(stderr, "Insufficient buffer memory on %s\n", dev_name);
        exit(EXIT_FAILURE);
    }

    buffers = calloc(req.count /*num of frames*/, sizeof(*buffers));

    if (!buffers) {
        fprintf(stderr, "Out of memory\n");
        exit(EXIT_FAILURE);
    }

    for (n_buffers = 0; n_buffers < req.count; ++n_buffers) {
        struct v4l2_buffer buf;
        struct v4l2_plane planes[VIDEO_MAX_PLANES]; /* struct v4l2_plane *planes */
        CLEAR(planes);
        CLEAR(buf);

        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = n_buffers;
        buf.length = n_planes;
        buf.m.planes = planes;

        if (-1 == xioctl(fd, VIDIOC_QUERYBUF, &buf))
            errno_exit("VIDIOC_QUERYBUF");
        for (unsigned int plane = 0; plane < n_planes; ++plane) {
            buffers[n_buffers].length[plane] = planes[plane].length;
            buffers[n_buffers].start[plane] =
                mmap(NULL /* start anywhere */,
                     planes[plane].length,
                     PROT_READ | PROT_WRITE /* required */,
                     MAP_SHARED /* recommended */,
                     fd,
                     planes[plane].m.mem_offset);

            if (MAP_FAILED == buffers[n_buffers].start[plane])
                errno_exit("mmap");
        }
    }
}
static void process_frame(const void* p, size_t size) {
    // TODO:

}

/**
 * @brief init device
 * 1. obtain device capabilities
 * 2. set buffer format
 * 3. set video input, video standard and tune
 * 4.
 */
static void init_device(void) {
    struct v4l2_capability cap;
    struct v4l2_cropcap cropcap;
    struct v4l2_crop crop;
    struct v4l2_format fmt;
    /* ------------------------device capabilities----------------------------- */
    CLEAR(cap);
    if (-1 == xioctl(fd, VIDIOC_QUERYCAP, &cap)) {
        if (EINVAL == errno) {
            fprintf(stderr, "request is not valid!\n");
            exit(EXIT_FAILURE);
        } else {
            fprintf(stderr, "Failed to query device capabilities!\n");
            exit(EXIT_FAILURE);
        }
    }
    // check if device supports capture
    unsigned int capabilities = cap.capabilities;
    if (cap.capabilities & V4L2_CAP_DEVICE_CAPS)
        capabilities = cap.device_caps;
    if (!(capabilities & V4L2_CAP_VIDEO_CAPTURE_MPLANE)) {
        fprintf(stderr, "Device does not support multi-planar capture\n");
        exit(EXIT_FAILURE);
    }
    if (!(capabilities & V4L2_CAP_STREAMING)) {
        fprintf(stderr, "Device does not support streaming I/O\n");
        exit(EXIT_FAILURE);
    }
    /* -----------select video input, video standard and tune here--------------*/
    CLEAR(cropcap);

    cropcap.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;

    if (0 == xioctl(fd, VIDIOC_CROPCAP, &cropcap)) {
        CLEAR(crop);
        crop.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        crop.c = cropcap.defrect; /* reset to default */

        if (-1 == xioctl(fd, VIDIOC_S_CROP, &crop)) {
            switch (errno) {
                case EINVAL:
                    /* Cropping not supported. */
                    break;
                default:
                    /* Errors ignored. */
                    break;
            }
        }
    } else {
        /* Errors ignored. */
    }
    /* ------------------------set buffer format------------------------------- */
    CLEAR(fmt);
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    if (force_format) {
        fmt.fmt.pix_mp.width = fwidth;
        fmt.fmt.pix_mp.height = fheight;
        fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_NV12;
        fmt.fmt.pix_mp.field = V4L2_FIELD_ANY;

        if (-1 == xioctl(fd, VIDIOC_S_FMT, &fmt)) {
            fprintf(stderr, "Failed to set buffer format\n");
            exit(EXIT_FAILURE);
        }
    } else {
        /* Preserve original settings as set by v4l2-ctl for example */
        if (-1 == xioctl(fd, VIDIOC_G_FMT, &fmt)) {
            fprintf(stderr, "Failed to get buffer format\n");
            exit(EXIT_FAILURE);
        }
    }
    n_planes = fmt.fmt.pix_mp.num_planes;
    if (n_planes == 0 || n_planes > VIDEO_MAX_PLANES) {
        fprintf(stderr, "Unsupported plane count: %u\n", n_planes);
        exit(EXIT_FAILURE);
    }

    init_mmap();
}
static int read_frame(void) {
    struct v4l2_buffer buf;
    struct v4l2_plane planes[VIDEO_MAX_PLANES];
    unsigned int i;

    CLEAR(buf);
    CLEAR(planes);
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    buf.memory = V4L2_MEMORY_MMAP;
    buf.length = n_planes;
    buf.m.planes = planes;

    if (-1 == xioctl(fd, VIDIOC_DQBUF, &buf)) {
        if (errno == EAGAIN)
            return 0;
        errno_exit("VIDIOC_DQBUF");
    }

    if (buf.index >= n_buffers || buf.length > n_planes) {
        fprintf(stderr, "Driver returned invalid buffer metadata\n");
        exit(EXIT_FAILURE);
    }

    for (i = 0; i < n_planes; ++i) {
        if (planes[i].bytesused > buffers[buf.index].length[i]) {
            fprintf(stderr, "Invalid bytesused for plane %u\n", i);
            exit(EXIT_FAILURE);
        }

        if (planes[i].data_offset > planes[i].bytesused) {
            fprintf(stderr, "Invalid data_offset for plane %u\n", i);
            exit(EXIT_FAILURE);
        }

        unsigned char* data =
            (unsigned char*)buffers[buf.index].start[i] + planes[i].data_offset;

        size_t payload_size = planes[i].bytesused - planes[i].data_offset;

        process_frame(data, payload_size);
    }

    if (-1 == xioctl(fd, VIDIOC_QBUF, &buf))
        errno_exit("VIDIOC_QBUF");

    return 1;
}

static void start_capturing(void) {
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;

    for (unsigned int i = 0; i < n_buffers; ++i) {
        struct v4l2_buffer buf;
        struct v4l2_plane planes[VIDEO_MAX_PLANES];

        CLEAR(buf);
        CLEAR(planes);
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        buf.length = n_planes;
        buf.m.planes = planes;

        if (-1 == xioctl(fd, VIDIOC_QBUF, &buf))
            errno_exit("VIDIOC_QBUF");
    }

    if (-1 == xioctl(fd, VIDIOC_STREAMON, &type))
        errno_exit("VIDIOC_STREAMON");
}

static void mainloop(void) {
    unsigned int count;

    count = frame_count;

    while (count-- > 0) {
        for (;;) {
            fd_set fds;
            struct timeval tv;
            int r;

            FD_ZERO(&fds);
            FD_SET(fd, &fds);

            /* Timeout. */
            tv.tv_sec = 2;
            tv.tv_usec = 0;

            r = select(fd + 1, &fds, NULL, NULL, &tv);

            if (-1 == r) {
                if (EINTR == errno)
                    continue;
                errno_exit("select");
            }

            if (0 == r) {
                fprintf(stderr, "select timeout\n");
                exit(EXIT_FAILURE);
            }

            if (read_frame())
                break;
            /* EAGAIN - continue select loop. */
        }
    }
}

static void stop_capturing(void) {
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;

    if (-1 == xioctl(fd, VIDIOC_STREAMOFF, &type))
        errno_exit("VIDIOC_STREAMOFF");
}
static void uninit_device(void) {
    for (unsigned int i = 0; i < n_buffers; ++i) {
        for (unsigned int plane = 0; plane < n_planes; ++plane) {
            if (-1 == munmap(buffers[i].start[plane], buffers[i].length[plane]))
                errno_exit("munmap");
        }
    }

    free(buffers);
}
static void close_device(void) {
    if (-1 == close(fd))
        errno_exit("close");

    fd = -1;
}
int main(int argc, char* argv[]) {
    if (argc < 2 || argc > 3) {
        fprintf(stderr, "Usage: %s DEVICE [OUTPUT_FILE]\n", argv[0]);
        return EXIT_FAILURE;
    }
    dev_name = argv[1];
    if (argc == 3) {
        if (freopen(argv[2], "wb", stdout) == NULL)
            errno_exit("freopen");
        out_buf = 1;
    }
    open_device();
    init_device();
    start_capturing();
    mainloop();
    stop_capturing();
    uninit_device();
    close_device();
    fprintf(stderr, "\n");
    return 0;
}
