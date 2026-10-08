/* SPDX-License-Identifier: GPL-2.0-or-later */
#define CONFIG_HAS_DMA 1
#define CONFIG_GENERIC_ALLOCATOR 1
#define PAGE_SIZE 4096UL
#define PAGE_ALIGN(n) (((n)+PAGE_SIZE-1)&~(PAGE_SIZE-1))
#define fallthrough __attribute__((fallthrough))
typedef unsigned int gfp_t;
#define __GFP_HIGHMEM 0
#define __GFP_COMP 0
#define __GFP_NORETRY 0
#define __GFP_NOWARN 0
#define pr_err(...) ((void)0)
#include "memalloc-constants.h"
struct gen_pool {int value;};
static struct gen_pool iram_pool;
static bool have_iram_pool,iram_allocation_success;
static inline struct gen_pool *of_gen_pool_get(void *node,const char *name,int index){(void)node;(void)name;(void)index;return have_iram_pool?&iram_pool:NULL;}
static inline unsigned char *gen_pool_dma_alloc_align(struct gen_pool *pool,size_t size,dma_addr_t *addr,int alignment){(void)pool;(void)alignment;if(!iram_allocation_success)return NULL;allocation_calls++;unsigned char *area=calloc(1,size);*addr=(uintptr_t)area;return area;}
static inline void gen_pool_free(struct gen_pool *pool,unsigned long area,size_t size){(void)pool;(void)size;free_calls++;free((void *)area);}
static inline gfp_t snd_mem_get_gfp_flags(struct device *device,gfp_t flags){(void)device;return flags;}
static inline void *alloc_pages_exact(size_t size,gfp_t flags){(void)flags;allocation_calls++;return calloc(1,size);}
static inline void *__vmalloc(size_t size,gfp_t flags){return alloc_pages_exact(size,flags);}
static inline void free_pages_exact(void *area,size_t size){(void)size;free_calls++;free(area);}
static inline void vfree(void *area){free_pages_exact(area,0);}
static inline void *dma_alloc_coherent(struct device *device,size_t size,dma_addr_t *addr,gfp_t flags){(void)device;void *area=alloc_pages_exact(size,flags);*addr=(uintptr_t)area;return area;}
static inline void dma_free_coherent(struct device *device,size_t size,void *area,dma_addr_t addr){(void)device;(void)addr;free_pages_exact(area,size);}
