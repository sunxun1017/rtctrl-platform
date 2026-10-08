// SPDX-License-Identifier: MIT
// Bounded RAM credential input and one-file transfer; no hardware/MCU access.
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>

static int hex(const char *p, size_t n) {
    for (size_t i = 0; i < n; ++i)
        if (!((p[i] >= '0' && p[i] <= '9') || (p[i] >= 'a' && p[i] <= 'f')))
            return 0;
    return 1;
}

static volatile sig_atomic_t interrupted;
static void stop_input(int signal_number) {
    interrupted = signal_number;
}

static int config(const char *path) {
    struct termios old, quiet;
    struct sigaction saved[3], action = {0};
    const int signals[3] = {SIGINT, SIGTERM, SIGHUP};
    int installed = 0, tty_quiet = 0;
    char input[140] = {0};
    int status = 1, fd = -1;
    if (tcgetattr(STDIN_FILENO, &old)) return 1;
    action.sa_handler = stop_input;
    sigemptyset(&action.sa_mask);
    interrupted = 0;
    for (int i = 0; i < 3; ++i) {
        if (sigaction(signals[i], &action, &saved[i])) goto done;
        installed++;
    }
    quiet = old;
    quiet.c_lflag &= ~(ECHO | ECHONL);
    if (tcsetattr(STDIN_FILENO, TCSANOW, &quiet)) goto done;
    tty_quiet = 1;
    if (interrupted) goto done;
    puts("CREDENTIAL_INPUT_READY_ECHO_OFF");
    fflush(stdout);
    struct pollfd ready = {STDIN_FILENO, POLLIN, 0};
    if (interrupted || poll(&ready, 1, 15000) != 1 || interrupted) goto done;
    ssize_t n = read(STDIN_FILENO, input, sizeof(input) - 1);
    if (n <= 0 || interrupted) goto done;
    input[n] = 0;
    char *newline = strchr(input, '\n');
    if (!newline) goto done;
    *newline = 0;
    char *colon = strchr(input, ':');
    if (!colon) goto done;
    *colon++ = 0;
    size_t ssid_length = strlen(input);
    if (!ssid_length || ssid_length > 64 || ssid_length % 2 || !hex(input, ssid_length)) goto done;
    if (strlen(colon) != 64 || !hex(colon, 64)) goto done;
    fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) goto done;
    if (dprintf(fd, "ctrl_interface=/tmp/wpa-control\nupdate_config=0\nnetwork={\n"
                   " ssid=%s\n psk=%s\n key_mgmt=WPA-PSK\n}\n", input, colon) < 0) goto done;
    if (!interrupted) status = 0;
done:
    if (status && tty_quiet) tcflush(STDIN_FILENO, TCIFLUSH);
    if (fd >= 0) {
        close(fd);
        if (status) unlink(path);
    }
    explicit_bzero(input, sizeof(input));
    if (tty_quiet && tcsetattr(STDIN_FILENO, TCSANOW, &old)) status = 1;
    for (int i = 0; i < installed; ++i) sigaction(signals[i], &saved[i], NULL);
    puts(status ? "CREDENTIAL_INPUT_FAILED" : "CREDENTIAL_RAM_FILE_READY_ECHO_RESTORED");
    return status;
}

static int read_all(int fd, void *buf, size_t n) {
    char *p = buf;
    while (n) {
        ssize_t k = read(fd, p, n);
        if (k <= 0) return -1;
        p += k;
        n -= (size_t)k;
    }
    return 0;
}

static int write_all(int fd, const void *buf, size_t n) {
    const char *p = buf;
    while (n) {
        ssize_t k = write(fd, p, n);
        if (k <= 0) return -1;
        p += k;
        n -= (size_t)k;
    }
    return 0;
}

static int serve(const char *path) {
    int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) return 1;
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons(18765),
                                 .sin_addr.s_addr = htonl(INADDR_ANY)};
    int reuse = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    if (bind(server, (struct sockaddr *)&address, sizeof(address)) || listen(server, 1)) {
        close(server);
        return 1;
    }
    puts("TRANSFER_SERVER_READY");
    fflush(stdout);
    int status = 1;
    for (int index = 0; index < 2; ++index) {
        struct pollfd ready = {server, POLLIN, 0};
        if (poll(&ready, 1, 60000) != 1) break;
        int client = accept(server, NULL, NULL);
        if (client < 0) break;
        struct timeval timeout = {.tv_sec = 15};
        setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
        char op;
        uint32_t length = 0;
        int file = -1, okay = 0, created = 0;
        if (read_all(client, &op, 1)) goto closed;
        if (index == 0 && op == 'P') {
            if (read_all(client, &length, sizeof(length))) goto closed;
            length = ntohl(length);
            if (!length || length > 262144) goto closed;
            file = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
            if (file < 0) goto closed;
            created = 1;
            char buffer[4096];
            while (length) {
                size_t count = length < sizeof(buffer) ? length : sizeof(buffer);
                if (read_all(client, buffer, count) || write_all(file, buffer, count)) goto closed;
                length -= count;
            }
            if (write_all(client, "OK\n", 3)) goto closed;
            okay = 1;
        } else if (index == 1 && op == 'G') {
            file = open(path, O_RDONLY | O_NOFOLLOW);
            struct stat st;
            if (file < 0 || fstat(file, &st) || !S_ISREG(st.st_mode) || st.st_size <= 0 || st.st_size > 262144) goto closed;
            length = htonl((uint32_t)st.st_size);
            if (write_all(client, &length, sizeof(length))) goto closed;
            char buffer[4096];
            ssize_t count;
            while ((count = read(file, buffer, sizeof(buffer))) > 0)
                if (write_all(client, buffer, (size_t)count)) goto closed;
            if (count < 0) goto closed;
            okay = 1;
            status = 0;
        }
closed:
        if (file >= 0) close(file);
        close(client);
        if (!okay && created) unlink(path);
        if (!okay) break;
    }
    close(server);
    puts(status ? "TRANSFER_FAILED" : "TRANSFER_ROUNDTRIP_COMPLETE");
    return status;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    signal(SIGPIPE, SIG_IGN);
    if (!strcmp(argv[1], "config")) return config(argv[2]);
    if (!strcmp(argv[1], "serve")) return serve(argv[2]);
    return 2;
}
