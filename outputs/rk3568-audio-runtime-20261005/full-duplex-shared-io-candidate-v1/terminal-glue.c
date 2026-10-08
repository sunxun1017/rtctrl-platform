/* SPDX-License-Identifier: MIT */
/* Primitive fixtures around extracted core teardown bodies, not kernel lists/PM. */
static void soc_remove_component(struct snd_soc_component *c, int probed);
static void snd_soc_unbind_card(struct snd_soc_card *card, bool unregister);
static void terminal_release_hook(void);
static bool list_empty(struct list_head *head) { return !head->count; }
static void list_add(struct list_head *item, struct list_head *head)
{ if (item->count) abort(); item->count = 1; head->count++; }
static void list_del(struct list_head *item)
{ if (!item->count) abort(); item->count = 0; if (unbind_card_list.count) unbind_card_list.count--; }
static void list_del_init(struct list_head *item) { item->count = 0; }
static void might_sleep(void) { }
static unsigned int msecs_to_jiffies(unsigned int ms) { return ms; }
#define spin_lock_irq(lock) pthread_mutex_lock(lock)
#define spin_unlock_irq(lock) pthread_mutex_unlock(lock)
static void terminal_wait(pthread_mutex_t *files_lock)
{
    file_waits++;
    int ret = pthread_mutex_trylock(&terminal_card.mutex.native);
    if (ret == EBUSY) wait_has_card_lock = true;
    else if (!ret) pthread_mutex_unlock(&terminal_card.mutex.native);
    else abort();
    ret = pthread_mutex_trylock(&codec.params_lock.native);
    if (ret == EBUSY) wait_has_params_lock = true;
    else if (!ret) pthread_mutex_unlock(&codec.params_lock.native);
    else abort();
    pthread_mutex_unlock(files_lock);
    terminal_release_hook();
    pthread_mutex_lock(files_lock);
}
#define wait_event_lock_irq_timeout(wq, condition, lock, timeout) \
    ({ (void)(wq); (void)(timeout); if (!(condition)) terminal_wait(&(lock)); (condition) ? 1L : 0L; })
#define wait_event_lock_irq(wq, condition, lock) \
    do { (void)(wq); if (!(condition)) terminal_wait(&(lock)); if (!(condition)) abort(); } while (0)
static struct snd_soc_component *snd_soc_lookup_component_nolocked(struct device *dev, const char *name)
{
    (void)name;
    int ret = pthread_mutex_trylock(&client_mutex.native);
    if (!ret) { pthread_mutex_unlock(&client_mutex.native); abort(); }
    if (ret != EBUSY) abort();
    helper_calls++;
    return component_registered && component.dev == dev ? &component : NULL;
}
static int snd_card_disconnect(struct snd_card *card)
{
    disconnect_calls++;
    printf("DISCONNECT %u %u %d\n", disconnect_calls, card->files_list.count, disconnect_error);
    if (disconnect_error) return disconnect_error;
    pthread_mutex_lock(&card->files_lock);
    card->shutdown = true; /* Fixture: actual API also disconnects devices/fops/IRQ. */
    pthread_mutex_unlock(&card->files_lock);
    return 0;
}
static void core_step(void)
{
    core_steps++;
    if (terminal_snd_card.files_list.count) core_before_file_drain = true;
}
static void snd_soc_component_remove(struct snd_soc_component *c)
{ core_step(); component_remove_calls++; rk817_remove(c); }
static void snd_soc_component_set_jack(struct snd_soc_component *c, void *jack, void *data)
{ (void)c; (void)jack; (void)data; core_step(); }
static void snd_soc_dapm_free(struct snd_soc_dapm_context *dapm) { (void)dapm; core_step(); }
static void soc_cleanup_component_debugfs(struct snd_soc_component *c) { (void)c; core_step(); }
static void snd_soc_component_module_put_when_remove(struct snd_soc_component *c) { (void)c; core_step(); }
static void soc_remove_link_dais(struct snd_soc_card *card) { (void)card; core_step(); }
static void soc_remove_link_components(struct snd_soc_card *card)
{ core_step(); cleanup_calls++; for (unsigned int i = 0; i < card->component_count; i++) soc_remove_component(card->components[i], 1); }
#define for_each_card_rtds_safe(card, rtd, n) \
    for (unsigned int model_i = 0; model_i < (card)->count && ((rtd) = (card)->rtds[model_i], (n) = NULL, (void)(n), true); model_i++)
static void snd_soc_remove_pcm_runtime(struct snd_soc_card *card, struct snd_soc_pcm_runtime *rtd)
{ (void)card; (void)rtd; core_step(); }
static void soc_remove_aux_devices(struct snd_soc_card *card) { (void)card; core_step(); }
static void soc_unbind_aux_dev(struct snd_soc_card *card) { (void)card; core_step(); }
static void soc_cleanup_card_debugfs(struct snd_soc_card *card) { (void)card; core_step(); }
static void snd_soc_card_remove(struct snd_soc_card *card) { (void)card; core_step(); }
static int snd_card_free(struct snd_card *card) { (void)card; core_step(); return 0; }
static void snd_soc_unregister_component(struct device *dev)
{
    (void)dev;
    unregister_calls++;
    printf("UNREGISTER %u\n", unregister_calls);
    mutex_lock(&client_mutex);
    if (component_registered) {
        /* Actual unregister_dais only deletes list nodes; devm memory remains. */
        if (component.card) snd_soc_unbind_card(component.card, false);
        component_registered = false;
    }
    mutex_unlock(&client_mutex);
}
