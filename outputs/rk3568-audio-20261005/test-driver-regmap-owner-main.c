/* SPDX-License-Identifier: GPL-2.0-or-later */
int main(int argc, char **argv)
{
    if (argc != 2)
        return 2;
    struct device parent = { 0 };
    struct regmap_config config = { .name = "rk817-codec" };
    struct regmap *map = calloc(1, sizeof(*map));
    if (!map || regmap_attach_dev(&parent, map, &config))
        return 2;
    if (!strcmp(argv[1], "child-exit-parent-lookup")) {
        rk817_regmap_release(map);
        /* Actual name matcher dereferences the freed parent's lookup target. */
        return dev_get_regmap_match(&parent, parent.lookup, "rk817-codec") ? 0 : 1;
    }
    if (!strcmp(argv[1], "parent-lifetime-lookup")) {
        int matched = dev_get_regmap_match(&parent, parent.lookup, "rk817-codec");
        /* Lookup remains live until the parent releases both devres records. */
        rk817_regmap_release(map);
        free(parent.lookup);
        return matched ? 0 : 1;
    }
    return 2;
}
