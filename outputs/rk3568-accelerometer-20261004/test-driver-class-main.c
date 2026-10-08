static int failures;
static void reset(void)
{
    create_fault = attr_fault = creates = attrs = removes = destroys = invalid = 0;
    sensor_class = NULL;
    memset(removed_ids, 0, sizeof(removed_ids));
}
static void check(const char *name, int got, int expected)
{
    printf("%s got=%d expected=%d %s\n", name, got, expected,
           got == expected ? "PASS" : "FAIL");
    failures += got != expected;
}
int main(void)
{
    reset();
    create_fault = -ENOMEM;
    check("class-create-error-propagated", sensor_class_init(), -ENOMEM);
    check("class-create-error-no-attrs", attrs, 0);
    check("class-create-error-no-invalid-pointer", invalid, 0);
    reset();
    create_fault = -ENOMEM;
    check("module-init-propagates-class-error", sensor_init(), -ENOMEM);
    reset();
    attr_fault = 1;
    check("first-attribute-error", sensor_init(), -EIO);
    check("first-attribute-destroy-class", destroys, 1);
    check("first-attribute-no-remove-uncreated", removes, 0);
    check("first-attribute-no-second-create", attrs, 1);
    reset();
    attr_fault = 2;
    check("second-attribute-error", sensor_init(), -EIO);
    check("second-attribute-destroy-class", destroys, 1);
    check("second-attribute-remove-first", removes, 1);
    check("second-attribute-remove-correct-id", removed_ids[0], 1);
    check("second-attribute-no-invalid-pointer", invalid, 0);
    reset();
    check("module-init-success", sensor_init(), 0);
    check("module-init-both-attributes", attrs, 2);
    check("module-init-keeps-class", destroys, 0);
    sensor_exit();
    check("module-exit-removes-both", removes, 2);
    check("module-exit-destroys-class", destroys, 1);
    check("module-exit-valid-class", invalid, 0);
    printf("TOTAL_FAILURES=%d\n", failures);
    return failures ? 1 : 0;
}
