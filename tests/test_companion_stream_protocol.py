# Execute the native framing parser without RKNN or audio capture.
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class StreamProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=shutil.which('g++')
        if not compiler: raise unittest.SkipTest('host C++ compiler unavailable')
        cls.tmp=tempfile.TemporaryDirectory()
        source=Path(cls.tmp.name)/'probe.cc'
        source.write_text(r'''
#include "stream_protocol.h"
#include <iostream>
int main(int argc,char** argv){if(argc==3){std::cout<<speech_stream::flush_steps(std::stoul(argv[1]),std::stoul(argv[2]));return 0;}try {speech_stream::Request r;while(speech_stream::read_request(std::cin,r))std::cout<<r.opcode<<":"<<r.payload.size()<<"\n";}catch(const std::exception& e){std::cerr<<e.what();return 2;}}
''')
        cls.binary=Path(cls.tmp.name)/'probe'
        subprocess.run([compiler,'-std=c++11','-I',str(ROOT/'scripts/speech-npu'),str(source),'-o',str(cls.binary)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def execute(self,data):
        return subprocess.run([str(self.binary)],input=data,capture_output=True,timeout=3)
    def test_multiple_requests_and_clean_eof(self):
        data=struct.pack('<IB',1920,1)+bytes(1920)+struct.pack('<IB',0,2)+struct.pack('<IB',0,3)+struct.pack('<IB',0,4)
        result=self.execute(data)
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout,b'1:1920\n2:0\n3:0\n4:0\n')
        self.assertEqual(self.execute(b'').returncode,0)
    def test_flush_real_frame_boundaries(self):
        for processed in (0, 96, 2880):
            for pending, expected in ((0,0),(1,1),(95,1),(96,1),(97,2),(102,2),(103,2),(192,2),(193,3)):
                with self.subTest(processed=processed,pending=pending):
                    result=subprocess.run([str(self.binary),str(processed),str(processed+pending)],capture_output=True,check=True,timeout=3)
                    self.assertEqual(int(result.stdout),expected)
                    self.assertGreaterEqual(processed+expected*96,processed+pending)
                    if expected: self.assertLess(processed+(expected-1)*96,processed+pending)
    def test_payload_boundary(self):
        self.assertEqual(self.execute(struct.pack('<IB',32000,1)+bytes(32000)).returncode,0)
        result=self.execute(struct.pack('<IB',32002,1))
        self.assertEqual(result.returncode,2)
        self.assertIn(b'exceeds',result.stderr)
    def test_truncation(self):
        for data in (b'\x00',struct.pack('<I',0),struct.pack('<IB',4,1)+b'\x00\x00'):
            with self.subTest(data=data): self.assertEqual(self.execute(data).returncode,2)
    def test_invalid_command_shapes(self):
        for size,op in ((0,1),(1,1),(2,2),(2,3),(2,4),(0,0),(0,5)):
            with self.subTest(size=size,op=op):
                self.assertEqual(self.execute(struct.pack('<IB',size,op)+bytes(size)).returncode,2)
if __name__=='__main__': unittest.main()
