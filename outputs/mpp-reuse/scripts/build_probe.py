from pathlib import Path
import subprocess
script=Path(__file__).with_name('build_mpp_test.py')
s=script.read_text()
s=s.replace("out=base/'plugin'", """p=source/'gstmpp.c'
code=p.read_text()
needle='  /* Prefer using dma fd */'
code=code.replace(needle, '''  static gint probe_once = 0;
  gboolean probe = g_atomic_int_compare_and_exchange (&probe_once, 0, 1);
  if (probe) {
    guint i;
    g_printerr ("RTCTRL_PROBE input memories=%u\\\\n", gst_buffer_n_memory (inbuf));
    for (i = 0; i < gst_buffer_n_memory (inbuf); ++i) {
      GstMemory *m = gst_buffer_peek_memory (inbuf, i);
      gsize offset, maxsize, size = gst_memory_get_sizes (m, &offset, &maxsize);
      g_printerr ("RTCTRL_PROBE memory=%u dmabuf=%d size=%zu offset=%zu maxsize=%zu\\\\n",
          i, gst_is_dmabuf_memory (m), size, offset, maxsize);
    }
  }
''' + needle)
needle='  dst_info.fd = gst_dmabuf_memory_get_fd (out_mem);'
code=code.replace(needle, '''  if (probe)
    g_printerr ("RTCTRL_PROBE RGA source=%s\\\\n", src_info.fd > 0 ? "dmabuf-fd" : "virtual-address");
''' + needle, 1)
p.write_text(code)
out=base/'probe-plugin'""")
Path('/tmp/build_probe_generated.py').write_text(s)
subprocess.run(['python3','/tmp/build_probe_generated.py'],check=True)
