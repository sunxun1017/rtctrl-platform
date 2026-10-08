/* SPDX-License-Identifier: GPL-2.0-or-later */
static uint32_t registers[0x1000/4];
static bool stall_kill;
static int go_commands,kill_commands,period_calls;
static atomic_int block_period;
static u32 readl(void *p){atomic_fetch_add(&mmio_calls,1);return *(u32 *)p;}
static void writel(u32 value,void *p){
 atomic_fetch_add(&mmio_calls,1);*(u32 *)p=value;ptrdiff_t offset=(char *)p-(char *)registers;
 if(offset==INTCLR)registers[ES/4]&=~value;
 if(offset==DBGCMD){
  unsigned opcode=(registers[DBGINST0/4]>>16)&0xff;
  if((opcode&0xfd)==CMD_DMAGO){unsigned chan=(registers[DBGINST0/4]>>24)&7;go_commands++;registers[CS(chan)/4]=DS_ST_EXEC;}
  if(opcode==CMD_DMAKILL){unsigned chan=(registers[DBGINST0/4]>>8)&7;kill_commands++;if(registers[DBGINST0/4]&1)registers[CS(chan)/4]=stall_kill?DS_ST_KILL:DS_ST_STOP;else registers[DS/4]=stall_kill?DS_ST_KILL:DS_ST_STOP;}
 }
}
static void snd_pcm_period_elapsed(struct snd_pcm_substream *s){(void)s;period_calls++;if(atomic_load(&block_period))boundary_pause();}
