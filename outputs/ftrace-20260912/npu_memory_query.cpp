#include <rknn_api.h>
#include <fstream>
#include <iostream>
#include <vector>
int main(int argc,char**argv){
 if(argc!=2){std::cerr<<"usage: npu_memory_query model.rknn\n";return 1;}
 std::ifstream f(argv[1],std::ios::binary|std::ios::ate);if(!f)return 1;
 auto n=f.tellg();if(n<=0||uint64_t(n)>UINT32_MAX)return 1;
 std::vector<char>b(static_cast<size_t>(n));f.seekg(0);f.read(b.data(),n);if(!f)return 1;
 rknn_context c=0;int r=rknn_init(&c,b.data(),b.size(),0,nullptr);std::cout<<"init_flags=0 init_ret="<<r<<'\n';if(r<0)return 1;
 rknn_sdk_version v{};r=rknn_query(c,RKNN_QUERY_SDK_VERSION,&v,sizeof(v));std::cout<<"version_ret="<<r;if(!r)std::cout<<" api="<<v.api_version<<" driver="<<v.drv_version;std::cout<<'\n';
 rknn_mem_size m{};r=rknn_query(c,RKNN_QUERY_MEM_SIZE,&m,sizeof(m));std::cout<<"mem_ret="<<r;if(!r)std::cout<<" weights="<<m.total_weight_size<<" internal="<<m.total_internal_size<<" dma="<<m.total_dma_allocated_size<<" total_sram="<<m.total_sram_size<<" free_sram="<<m.free_sram_size;std::cout<<'\n';
 int d=rknn_destroy(c);std::cout<<"destroy_ret="<<d<<" inference_not_run=1\n";return r<0||d<0?1:0;
}
