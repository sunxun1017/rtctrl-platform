#include <asm-generic/errno-base.h>
#include <assert.h>
#include <err.h>
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

#define REQUEST_BUFFER_COUNT 4
#define CLEAR(x) memset(&(x), 0, sizeof(x))
#define fwidth 2112
#define fheight 1568
#define FMT_NUM_PLANES 5
struct buffer {
    void* start[FMT_NUM_PLANES];
    size_t length;
};
enum io_method { IO_METHOD_READ, IO_METHOD_MMAP, IO_METHOD_USERPTR };
static char* dev_name;
static enum io_method io = IO_METHOD_MMAP;
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

static void init_read(unsigned int buffer_size) {
    buffers = calloc(1, sizeof(*buffers));

    if (!buffers) {
        fprintf(stderr, "Out of memory\n");
        exit(EXIT_FAILURE);
    }

    buffers[0].length = buffer_size;
    buffers[0].start = malloc(buffer_size);

    if (!buffers[0].start) {
        fprintf(stderr, "Out of memory\n");
        exit(EXIT_FAILURE);
    }
}

static void init_mmap(void) {
    struct v4l2_requestbuffers req;

    CLEAR(req);

    req.count = 4;
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
        struct v4l2_plane planes[FMT_NUM_PLANES];   /* struct v4l2_plane *planes */

        CLEAR(buf);

        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = n_buffers;
        buf.m.planes = planes;

        if (-1 == xioctl(fd, VIDIOC_QUERYBUF, &buf))
            errno_exit("VIDIOC_QUERYBUF");
        for (n_planes = 0; n_planes < FMT_NUM_PLANES; ++n_planes) {
            buffers[n_buffers].length = buf.length;
            buffers[n_buffers].start[n_planes] = mmap(NULL /* start anywhere */,
                                            buf.m.planes[n_planes].length,
                                            PROT_READ | PROT_WRITE /* required */,
                                            MAP_SHARED /* recommended */,
                                            fd,
                                            buf.m.planes[n_planes].m.mem_offset);

            if (MAP_FAILED == buffers[n_buffers].start[n_planes])
                errno_exit("mmap");
        }
    }
}
static void process_image(const void* p, size_t size) {
    if (out_buf)
        fwrite(p, size, 1, stdout);

    fflush(stderr);
    fprintf(stderr, ".");
    fflush(stdout);
}

static void init_userp(unsigned int buffer_size) {
    struct v4l2_requestbuffers req;

    CLEAR(req);

    req.count = 4;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    req.memory = V4L2_MEMORY_USERPTR;

    if (-1 == xioctl(fd, VIDIOC_REQBUFS, &req)) {
        if (EINVAL == errno) {
            fprintf(stderr,
                    "%s does not support "
                    "user pointer i/o\n",
                    dev_name);
            exit(EXIT_FAILURE);
        } else {
            errno_exit("VIDIOC_REQBUFS");
        }
    }

    buffers = calloc(4, sizeof(*buffers));

    if (!buffers) {
        fprintf(stderr, "Out of memory\n");
        exit(EXIT_FAILURE);
    }

    for (n_buffers = 0; n_buffers < 4; ++n_buffers) {
        buffers[n_buffers].length = buffer_size;
        buffers[n_buffers].start = malloc(buffer_size);

        if (!buffers[n_buffers].start) {
            fprintf(stderr, "Out of memory\n");
            exit(EXIT_FAILURE);
        }
    }
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
    unsigned int min;
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
    if (!(cap.capabilities & V4L2_CAP_VIDEO_CAPTURE)) {
        fprintf(stderr, "Device does not support capture\n");
        exit(EXIT_FAILURE);
    }
    // check if device supports the selected I/O method
    switch (io) {
        case IO_METHOD_READ:
            /* Handle read method */
            if (cap.capabilities & IO_METHOD_READ) {
                fprintf(stderr, "Device supports read method\n");
            }
            break;
        case IO_METHOD_MMAP:
            /* Handle mmap method */
            if (cap.capabilities & IO_METHOD_MMAP) {
                fprintf(stderr, "Device supports mmap method\n");
            }
            break;
        case IO_METHOD_USERPTR:
            /* Handle userptr method */
            if (cap.capabilities & IO_METHOD_USERPTR) {
                fprintf(stderr, "Device supports userptr method\n");
            }
            break;
    }
    /* -----------select video input, video standard and tune here--------------*/
    CLEAR(cropcap);

    cropcap.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;

    if (0 == xioctl(fd, VIDIOC_CROPCAP, &cropcap)) {
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
    /* Buggy driver paranoia. */
    min = fmt.fmt.pix.width * 2;
    if (fmt.fmt.pix.bytesperline < min)
        fmt.fmt.pix.bytesperline = min;
    min = fmt.fmt.pix.bytesperline * fmt.fmt.pix.height;
    if (fmt.fmt.pix.sizeimage < min)
        fmt.fmt.pix.sizeimage = min;

    switch (io) {
        case IO_METHOD_READ:
            init_read(fmt.fmt.pix.sizeimage);
            break;

        case IO_METHOD_MMAP:
            init_mmap();
            break;

        case IO_METHOD_USERPTR:
            init_userp(fmt.fmt.pix.sizeimage);
            break;
    }
}
static int read_frame(void) {
    struct v4l2_buffer buf;
    unsigned int i;

    switch (io) {
        case IO_METHOD_READ:
            if (-1 == read(fd, buffers[0].start, buffers[0].length)) {
                switch (errno) {
                    case EAGAIN:
                        return 0;

                    case EIO:
                        /* Could ignore EIO, see spec. */

                        /* fall through */

                    default:
                        errno_exit("read");
                }
            }

            process_image(buffers[0].start, buffers[0].length);
            break;

        case IO_METHOD_MMAP:
            CLEAR(buf);

            buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
            buf.memory = V4L2_MEMORY_MMAP;

            if (-1 == xioctl(fd, VIDIOC_DQBUF, &buf)) {
                switch (errno) {
                    case EAGAIN:
                        return 0;

                    case EIO:
                        /* Could ignore EIO, see spec. */

                        /* fall through */

                    default:
                        errno_exit("VIDIOC_DQBUF");
                }
            }

            assert(buf.index < n_buffers);

            process_image(buffers[buf.index].start, buf.bytesused);

            if (-1 == xioctl(fd, VIDIOC_QBUF, &buf))
                errno_exit("VIDIOC_QBUF");
            break;

        case IO_METHOD_USERPTR:
            CLEAR(buf);

            buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
            buf.memory = V4L2_MEMORY_USERPTR;

            if (-1 == xioctl(fd, VIDIOC_DQBUF, &buf)) {
                switch (errno) {
                    case EAGAIN:
                        return 0;

                    case EIO:
                        /* Could ignore EIO, see spec. */

                        /* fall through */

                    default:
                        errno_exit("VIDIOC_DQBUF");
                }
            }

            for (i = 0; i < n_buffers; ++i)
                if (buf.m.userptr == (unsigned long)buffers[i].start &&
                    buf.length == buffers[i].length)
                    break;

            assert(i < n_buffers);

            process_image((void*)buf.m.userptr, buf.bytesused);

            if (-1 == xioctl(fd, VIDIOC_QBUF, &buf))
                errno_exit("VIDIOC_QBUF");
            break;
    }

    return 1;
}

static void start_capturing(void) {
    {
        unsigned int i;
        enum v4l2_buf_type type;

        switch (io) {
            case IO_METHOD_READ:
                /* Nothing to do. */
                break;

            case IO_METHOD_MMAP:
                for (i = 0; i < n_buffers; ++i) {
                    struct v4l2_buffer buf;

                    CLEAR(buf);
                    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
                    buf.memory = V4L2_MEMORY_MMAP;
                    buf.index = i;

                    if (-1 == xioctl(fd, VIDIOC_QBUF, &buf))
                        errno_exit("VIDIOC_QBUF");
                }
                type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
                if (-1 == xioctl(fd, VIDIOC_STREAMON, &type))
                    errno_exit("VIDIOC_STREAMON");
                break;

            case IO_METHOD_USERPTR:
                for (i = 0; i < n_buffers; ++i) {
                    struct v4l2_buffer buf;

                    CLEAR(buf);
                    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
                    buf.memory = V4L2_MEMORY_USERPTR;
                    buf.index = i;
                    buf.m.userptr = (unsigned long)buffers[i].start;
                    buf.length = (__u32)buffers[i].length;

                    if (-1 == xioctl(fd, VIDIOC_QBUF, &buf))
                        errno_exit("VIDIOC_QBUF");
                }
                type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
                if (-1 == xioctl(fd, VIDIOC_STREAMON, &type))
                    errno_exit("VIDIOC_STREAMON");
                break;
        }
    }
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
    enum v4l2_buf_type type;

    switch (io) {
        case IO_METHOD_READ:
            /* Nothing to do. */
            break;

        case IO_METHOD_MMAP:
        case IO_METHOD_USERPTR:
            type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
            if (-1 == xioctl(fd, VIDIOC_STREAMOFF, &type))
                errno_exit("VIDIOC_STREAMOFF");
            break;
    }
}
static void uninit_device(void) {
    unsigned int i;

    switch (io) {
        case IO_METHOD_READ:
            free(buffers[0].start);
            break;

        case IO_METHOD_MMAP:
            for (i = 0; i < n_buffers; ++i)
                if (-1 == munmap(buffers[i].start, buffers[i].length))
                    errno_exit("munmap");
            break;

        case IO_METHOD_USERPTR:
            for (i = 0; i < n_buffers; ++i)
                free(buffers[i].start);
            break;
    }

    free(buffers);
}
static void close_device(void) {
    if (-1 == close(fd))
        errno_exit("close");

    fd = -1;
}
int main(void) {
    // TODO: identify the device
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
