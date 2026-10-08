/* Minimal prtd shape used by five actual DMA seam bodies, not full kernel layout. */
struct dmaengine_pcm_runtime_data {
    struct dma_chan *dma_chan; bool checked; int first_error;
    void (*error_sink)(struct snd_pcm_substream *, int, void *); void *error_sink_arg;
    spinlock_t lifecycle_lock;
};
static int seam_cached_error, seam_check_result;
static unsigned int seam_cached_checks, seam_borrow_after_notify;
static bool seam_at_GO;
static int dmaengine_check_open(struct dma_chan *chan) { (void)chan;seam_cached_checks++;return seam_cached_error; }
