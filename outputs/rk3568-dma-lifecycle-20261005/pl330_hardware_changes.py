#!/usr/bin/env python3
"""Bounded PL330 debug commands and state waits; no implicit reset proof."""
from source_utils import function, replace

WAIT = '''/* Caller holds the controller lock; this atomic wait always has a deadline. */
static int pl330_wait_state(struct pl330_thread *thrd, u32 states,
			    unsigned int timeout_ms)
{
	ktime_t deadline = ktime_add_ms(ktime_get(), timeout_ms);

	if (thrd->dmac->pm_failed)
		return thrd->dmac->lifecycle_error;
	do {
		if (_state(thrd) & states)
			return 0;
		cpu_relax();
	} while (ktime_compare(ktime_get(), deadline) < 0);
	pl330_error_locked(thrd->dmac, -ETIMEDOUT);
	return -ETIMEDOUT;
}

'''

STOP = '''static int _stop(struct pl330_thread *thrd)
{
	struct pl330_dmac *pl330 = thrd->dmac;
	void __iomem *regs = pl330->base;
	u8 insn[6] = {0, 0, 0, 0, 0, 0};
	u32 state, inten;
	int ret;

	if (pl330->pm_failed)
		return pl330->lifecycle_error;
	/* Cut the event even when a KILL is already in progress or STOPPED. */
	if (!is_manager(thrd)) {
		inten = readl(regs + INTEN);
		writel(inten & ~(1U << thrd->ev), regs + INTEN);
		writel(1U << thrd->ev, regs + INTCLR);
	}
	state = _state(thrd);
	if (state == PL330_STATE_FAULT_COMPLETING) {
		ret = pl330_wait_state(thrd, PL330_STATE_FAULTING |
			PL330_STATE_KILLING | PL330_STATE_STOPPED, 5);
		if (ret)
			return ret;
		state = _state(thrd);
	}
	if (state == PL330_STATE_COMPLETING || state == PL330_STATE_KILLING ||
	    state == PL330_STATE_STOPPED)
		return 0;
	if (state == PL330_STATE_INVALID) {
		pl330_error_locked(pl330, -EIO);
		return -EIO;
	}
	_emit_KILL(0, insn);
	/* A successful request is distinct from the process-context STOPPED proof. */
	return _execute_DBGINSN(thrd, insn, is_manager(thrd));
}'''

START = '''static bool _start(struct pl330_thread *thrd)
{
	int ret;

	if (thrd->dmac->lifecycle_error || !thrd->accept_callbacks)
		return false;
	switch (_state(thrd)) {
	case PL330_STATE_FAULT_COMPLETING:
		ret = pl330_wait_state(thrd, PL330_STATE_FAULTING |
			PL330_STATE_KILLING | PL330_STATE_STOPPED, 5);
		if (ret)
			return false;
		if (_state(thrd) == PL330_STATE_KILLING &&
		    pl330_wait_state(thrd, PL330_STATE_STOPPED, 5))
			return false;
		fallthrough;
	case PL330_STATE_FAULTING:
		if (_stop(thrd))
			return false;
		fallthrough;
	case PL330_STATE_KILLING:
	case PL330_STATE_COMPLETING:
		if (pl330_wait_state(thrd, PL330_STATE_STOPPED, 5))
			return false;
		fallthrough;
	case PL330_STATE_STOPPED:
		return _trigger(thrd);
	case PL330_STATE_WFP:
	case PL330_STATE_QUEUEBUSY:
	case PL330_STATE_ATBARRIER:
	case PL330_STATE_UPDTPC:
	case PL330_STATE_CACHEMISS:
	case PL330_STATE_EXECUTING:
		return true;
	case PL330_STATE_WFE:
	default:
		return false;
	}
}'''


def bounded_hardware(source):
    source = replace(source, "#include <linux/refcount.h>", "#include <linux/refcount.h>\n#include <linux/ktime.h>\n#include <asm/unaligned.h>")
    source = replace(source, "#define UNTIL(t, s)\twhile (!(_state(t) & (s))) cpu_relax();", "/* State waits use pl330_wait_state with an explicit deadline. */")
    old = function(source, "_until_dmac_idle")
    new = '''static bool _until_dmac_idle(struct pl330_thread *thrd)
{
	void __iomem *regs = thrd->dmac->base;
	ktime_t deadline = ktime_add_ms(ktime_get(), 5);

	do {
		if (!(readl(regs + DBGSTATUS) & DBG_BUSY))
			return false;
		cpu_relax();
	} while (ktime_compare(ktime_get(), deadline) < 0);
	return true;
}'''
    source = replace(source, old, "static void pl330_error_locked(struct pl330_dmac *pl330, int error);\n\n" + new)
    old = function(source, "_execute_DBGINSN")
    new = replace(old, "static inline void _execute_DBGINSN", "static inline int _execute_DBGINSN")
    new = replace(new, "\tu32 val;", "\tu32 val;\n\n\tif (thrd->dmac->pm_failed)\n\t\treturn thrd->dmac->lifecycle_error;")
    new = replace(new, "\t\treturn;", "\t\tpl330_error_locked(thrd->dmac, -ETIMEDOUT);\n\t\treturn -ETIMEDOUT;")
    new = replace(new, "le32_to_cpu(*((__le32 *)&insn[2]))", "get_unaligned_le32(&insn[2])")
    new = replace(new, "\twritel(0, regs + DBGCMD);", "\twritel(0, regs + DBGCMD);\n\treturn 0;")
    source = replace(source, old, new)
    old = function(source, "_state")
    new = replace(old, "\tu32 val;", "\tu32 val;\n\n\tif (thrd->dmac->pm_failed)\n\t\treturn PL330_STATE_INVALID;")
    source = replace(source, old, new)
    source = replace(source, function(source,"_stop"), WAIT + STOP)
    old = function(source, "_trigger")
    new = replace(old, "\tint idx;", "\tint idx, ret;\n\tu32 inten;\n\n\tif (thrd->dmac->lifecycle_error || !thrd->accept_callbacks)\n\t\treturn false;")
    new = replace(new, "\twritel(readl(regs + INTEN) | (1 << thrd->ev), regs + INTEN);", "\tinten = readl(regs + INTEN);\n\twritel(inten | (1U << thrd->ev), regs + INTEN);")
    new = replace(new, "\t_execute_DBGINSN(thrd, insn, true);", "\tret = _execute_DBGINSN(thrd, insn, true);\n\tif (ret) {\n\t\twritel(inten & ~(1U << thrd->ev), regs + INTEN);\n\t\twritel(1U << thrd->ev, regs + INTCLR);\n\t\treturn false;\n\t}")
    source = replace(source, old, new)
    source = replace(source, function(source,"_start"), START)
    if "UNTIL(" in source:raise ValueError("unbounded UNTIL survived")
    return source
