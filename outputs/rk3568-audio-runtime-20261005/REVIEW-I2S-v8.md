# I2S v8 独立审查发现与修正入口

冻结源SHA `33bd1208d379be53be8232cab11fe908f2d3096b94e66fc59d76a143c86cb3d0`。
以下发现由主控复核实际报告和源字节，原复现目录逐文件保存在
[独立复现](build/i2s-v8-independent-review/result.json)。这不是已完成的全驱动审查。

真实v8 clock_release action在probe中早于devm_clk_get TX/RX注册。devres逆序释放会先
释放clock consumer handle，再调用action中的disable；实际提取回调及逆序释放模型
在ASan发生heap-use-after-free，运行exit1，错误日志SHA
`b8040a60a5266ec413d2da10df3c9764dee3eba06806ea8e86f694c9474893b0`。
边界模型没有实体硬件，不能当作板端已发生，但源注册顺序确实使该路径可达。

已注册的legacy loopback控制未受checked profile的状态门控：running+configuring仍
返回0并把硬件模式写成4，sticky错误+失败PM仍返回0并改缓存为8；读失败get也返回0。
真实回调复现stdout SHA `cb652c3b71bcad8bcc8dafd2431d3665b661685c7ee39bf1fd91c3082c5280ec`。

作者在独立review-revision目录修正clock action顺序、撤掉checked profile的legacy控制，
并补完整真实probe、注册失败的devres逆序回退、ready发布窗口、PM重入和remove边界。
v8/sealed-v1保持原字节。新版本完成编译和冻结后另行独立审查；当前无Image或板端START放行。
