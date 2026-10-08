/* SPDX-License-Identifier: MIT */
/* Inspect cached ALSA control values only; no PCM, control writes, or retries. */
#define _GNU_SOURCE
#include <fcntl.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <signal.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#ifdef ALSA_LOCKED_UAPI
#include ALSA_LOCKED_UAPI
#else
#include <sound/asound.h>
#endif

_Static_assert(sizeof(void *) == 8, "native 64-bit pointers required");
_Static_assert(sizeof(struct snd_ctl_card_info) == 376, "CARD_INFO ABI");
_Static_assert(sizeof(struct snd_ctl_elem_id) == 64, "ELEM_ID ABI");
_Static_assert(sizeof(struct snd_ctl_elem_list) == 80, "ELEM_LIST ABI");
_Static_assert(offsetof(struct snd_ctl_elem_list, pids) == 16, "LIST pids offset");
_Static_assert(sizeof(struct snd_ctl_elem_info) == 272, "ELEM_INFO ABI");
_Static_assert(offsetof(struct snd_ctl_elem_info, value) == 80, "INFO value offset");
_Static_assert(sizeof(struct snd_ctl_elem_value) == 1224, "ELEM_VALUE ABI");
_Static_assert(offsetof(struct snd_ctl_elem_value, value) == 72, "READ value offset");
_Static_assert(SNDRV_CTL_IOCTL_CARD_INFO == 0x81785501UL, "CARD_INFO ioctl");
_Static_assert(SNDRV_CTL_IOCTL_ELEM_LIST == 0xc0505510UL, "LIST ioctl");
_Static_assert(SNDRV_CTL_IOCTL_ELEM_INFO == 0xc1105511UL, "INFO ioctl");
_Static_assert(SNDRV_CTL_IOCTL_ELEM_READ == 0xc4c85512UL, "READ ioctl");

enum { MAX_CONTROLS = 64, MAX_ITEMS = 64, TARGET_CONTROLS = 3 };
static const char *const target_names[TARGET_CONTROLS] = {
    "Playback Path", "Capture MIC Path", "Resume Path"
};
static const char *const target_off[TARGET_CONTROLS] = {"OFF", "MIC OFF", NULL};

struct inspected_control {
    struct snd_ctl_elem_id id;
    unsigned int present;
    unsigned int items;
    unsigned int value;
    char labels[MAX_ITEMS][64];
};

/* Bound all kernel strings before comparing or emitting them. */
static int text_valid(const void *data, size_t size, int allow_empty)
{
    const unsigned char *text = data;
    for (size_t i = 0; i < size; i++) {
        if (!text[i]) {
            return i != 0 || allow_empty;
        }
        if (text[i] < 0x20 || text[i] > 0x7e) {
            return 0;
        }
    }
    return 0;
}

static int card_valid(const struct snd_ctl_card_info *info, int card)
{
    static const unsigned char required_id[16] = "rockchiprk809co";
    return info->card == card && !memcmp(info->id, required_id, sizeof(required_id)) &&
           text_valid(info->driver, sizeof(info->driver), 1) &&
           text_valid(info->name, sizeof(info->name), 1) &&
           text_valid(info->longname, sizeof(info->longname), 1) &&
           text_valid(info->mixername, sizeof(info->mixername), 1) &&
           text_valid(info->components, sizeof(info->components), 1);
}

static int list_targets(const struct snd_ctl_elem_id *ids, unsigned int count,
                        struct inspected_control *controls)
{
    for (unsigned int i = 0; i < count; i++) {
        const struct snd_ctl_elem_id *id = &ids[i];
        if (!id->numid || id->iface < SNDRV_CTL_ELEM_IFACE_CARD ||
            id->iface > SNDRV_CTL_ELEM_IFACE_LAST ||
            !text_valid(id->name, sizeof(id->name), 0)) {
            return 0;
        }
        for (unsigned int j = 0; j < i; j++) {
            if (id->numid == ids[j].numid) {
                return 0;
            }
        }
        for (unsigned int t = 0; t < TARGET_CONTROLS; t++) {
            if (!strcmp((const char *)id->name, target_names[t])) {
                if (controls[t].present || id->iface != SNDRV_CTL_ELEM_IFACE_MIXER ||
                    id->device || id->subdevice || id->index) {
                    return 0;
                }
                controls[t].id = *id;
                controls[t].present = 1;
            }
        }
    }
    return controls[0].present && controls[1].present;
}

static int inspect_control(int fd, struct inspected_control *control, const char *off_label)
{
    unsigned int expected_access = 0;
    unsigned int off_item = UINT_MAX;
    unsigned int off_matches = 0;
    /* Item zero supplies the bound; subsequent calls must retain that metadata. */
    for (unsigned int item = 0; item == 0 || item < control->items; item++) {
        struct snd_ctl_elem_info info;
        memset(&info, 0, sizeof(info));
        info.id = control->id;
        info.type = SNDRV_CTL_ELEM_TYPE_NONE;
        info.count = UINT_MAX;
        info.value.enumerated.items = UINT_MAX;
        info.value.enumerated.item = item;
        memset(info.value.enumerated.name, 0xff, sizeof(info.value.enumerated.name));
        if (ioctl(fd, SNDRV_CTL_IOCTL_ELEM_INFO, &info) != 0 ||
            memcmp(&info.id, &control->id, sizeof(info.id)) ||
            info.type != SNDRV_CTL_ELEM_TYPE_ENUMERATED ||
            !(info.access & SNDRV_CTL_ELEM_ACCESS_READ) || info.count != 1 ||
            !info.value.enumerated.items || info.value.enumerated.items > MAX_ITEMS ||
            info.value.enumerated.item != item ||
            !text_valid(info.value.enumerated.name, sizeof(info.value.enumerated.name), 0)) {
            return 0;
        }
        if (item == 0) {
            control->items = info.value.enumerated.items;
            expected_access = info.access;
        } else if (info.value.enumerated.items != control->items ||
                   info.access != expected_access) {
            return 0;
        }
        memcpy(control->labels[item], info.value.enumerated.name, sizeof(control->labels[item]));
        if (off_label && !strcmp(control->labels[item], off_label)) {
            off_matches++;
            off_item = item;
        }
    }
    if (off_label && off_matches != 1) {
        return 0;
    }
    struct snd_ctl_elem_value value;
    memset(&value, 0, sizeof(value));
    value.id = control->id;
    value.value.enumerated.item[0] = UINT_MAX;
    if (ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &value) != 0 ||
        memcmp(&value.id, &control->id, sizeof(value.id)) || value.indirect ||
        value.value.enumerated.item[0] >= control->items ||
        (off_label && value.value.enumerated.item[0] != off_item)) {
        return 0;
    }
    control->value = value.value.enumerated.item[0];
    return 1;
}

int main(int argc, char **argv)
{
    if (argc != 4 || strcmp(argv[1], "--inspect") || strcmp(argv[2], "--card") ||
        strlen(argv[3]) != 1 || argv[3][0] < '0' || argv[3][0] > '7') {
        fprintf(stderr, "usage: alsa-inspect --inspect --card N (N=0..7)\n");
        return 2;
    }
    const int card = argv[3][0] - '0';
    struct sigaction timeout_action;
    memset(&timeout_action, 0, sizeof(timeout_action));
    timeout_action.sa_handler = SIG_DFL;
    if (sigemptyset(&timeout_action.sa_mask) != 0 ||
        sigaction(SIGALRM, &timeout_action, NULL) != 0) {
        fprintf(stderr, "ALSA inspection failed: establish SIGALRM deadline\n");
        return 2;
    }
    /* Default SIGALRM terminates blocked calls and the kernel releases the fd. */
    alarm(5);
    char path[32];
    snprintf(path, sizeof(path), "/dev/snd/controlC%d", card);
    int fd = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NOCTTY);
    if (fd < 0) {
        alarm(0);
        fprintf(stderr, "ALSA inspection failed: open control node\n");
        return 2;
    }
    int verified = 0;
    const char *failure = "control node identity";
    struct stat st;
    struct snd_ctl_card_info card_info;
    struct snd_ctl_elem_id ids[MAX_CONTROLS];
    struct inspected_control controls[TARGET_CONTROLS];
    memset(controls, 0, sizeof(controls));
    if (fstat(fd, &st) != 0 || !S_ISCHR(st.st_mode) || major(st.st_rdev) != 116) {
        goto done;
    }
    failure = "card identity or card strings";
    memset(&card_info, 0xff, sizeof(card_info));
    if (ioctl(fd, SNDRV_CTL_IOCTL_CARD_INFO, &card_info) != 0 || !card_valid(&card_info, card)) {
        goto done;
    }
    failure = "first control list";
    struct snd_ctl_elem_list list;
    memset(&list, 0, sizeof(list));
    list.used = UINT_MAX;
    list.count = UINT_MAX;
    if (ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list) != 0 || list.offset || list.space ||
        list.pids || list.used || list.count < 2 || list.count > MAX_CONTROLS) {
        goto done;
    }
    const unsigned int count = list.count;
    failure = "second control list";
    memset(ids, 0xff, sizeof(ids));
    memset(&list, 0, sizeof(list));
    list.space = count;
    list.pids = ids;
    list.used = UINT_MAX;
    list.count = UINT_MAX;
    if (ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list) != 0 || list.offset || list.space != count ||
        list.pids != ids || list.count != count || list.used != count) {
        goto done;
    }
    failure = "control identifiers or required control names";
    if (!list_targets(ids, count, controls)) {
        goto done;
    }
    failure = "control metadata, enum labels, or cached path value";
    for (unsigned int t = 0; t < TARGET_CONTROLS; t++) {
        if (controls[t].present && !inspect_control(fd, &controls[t], target_off[t])) {
            goto done;
        }
    }
    verified = 1;

done:
    const int close_status = close(fd);
    alarm(0);
    if (close_status != 0) {
        fprintf(stderr, "ALSA inspection failed: close control node\n");
        return 2;
    }
    if (!verified) {
        fprintf(stderr, "ALSA inspection failed: %s\n", failure);
        return 2;
    }
    printf("ALSA_CARD card=%d id=%s controls=%u\n", card, card_info.id, count);
    for (unsigned int i = 0; i < count; i++) {
        printf("ALSA_LIST numid=%u iface=%d device=%u subdevice=%u index=%u name=%s\n",
               ids[i].numid, ids[i].iface, ids[i].device, ids[i].subdevice, ids[i].index, ids[i].name);
    }
    for (unsigned int t = 0; t < TARGET_CONTROLS; t++) {
        if (controls[t].present) {
            printf("ALSA_CONTROL numid=%u name=%s items=%u value=%u label=%s\n",
                   controls[t].id.numid, controls[t].id.name, controls[t].items, controls[t].value,
                   controls[t].labels[controls[t].value]);
        }
    }
    puts("ALSA_CODEC_INTERFACE_VERIFIED");
    return 0;
}
