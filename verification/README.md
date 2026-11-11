独立验收说明

冻结提交：https://github.com/9873199/lxml-restricted-xslt/commit/3a1c4476ffe0692867fa9909c0acdadbe1a44af7
实际解释器：3.14.3 (tags/v3.14.3:323c59a, Feb  3 2026, 16:04:56) [MSC v.1944 64 bit (AMD64)]

先检出冻结提交，使用environment-reviewed.json中的真实Python和依赖。按replay/r3/build-config.json准备Windows MSVC/SDK和static-dependencies.json列明的静态依赖包；在较短的缓存目录重编译，PIP_CONFIG_FILE=NUL，命令行只传一次editable_mode=strict。import-source.log显示独立源码生成的.pyd实际路径，replay-proof.json证明源码字节未变。按各verification目录的*-command.json执行；acceptance_adapter.py只映射公开API，不补安全逻辑。相关回归117项和15子测试不与独立38项相加冒充原轨成绩。external-env-r1保留未修改上游测试、动态库探针、真实失败和文档示例结果；Windows静态构建未满足该外部动态libxml2测试前提，不忽略或伪写全过。所有临时文件、XML、日志、构建及本机服务夹具都放缓存；无需容器、远程服务或外部证书。

每组目录内的 *-command.json 保留真实参数、工作目录、PYTHONPATH、退出码和原始日志位置；test-results.json 与 JUnit XML 保留完整成绩。跨机器运行时把这些绝对路径映射到同一冻结 checkout 和自己的缓存目录，所有 --basetemp、XML 和构建输出均放在缓存里。依赖版本见 environment-reviewed.json。
这些材料在模型单轮结束后生成，与原轨内测试分开，不代表项目方质检通过。原轨和视频只放各自的飞书附件。


冻结产物提交：https://github.com/9873199/lxml-restricted-xslt/commit/3a1c4476ffe0692867fa9909c0acdadbe1a44af7
这些独立验收文件在模型首轮结束后生成，不是模型原轨中的测试。
