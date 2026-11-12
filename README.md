# 服务商品MHTML留存的资源作用域采集

这是商品与服务履约资料的独立Python工具。`data/`保存合成报文、导出文件或解码服务响应，`source_data.io`读取清单并核对原文件身份，`source_data.domain`提供原始资料概况，`source_data.replay`按记录返回响应，`source_data.cli`显示JSON摘要。字段与来源格式见[资料约定](docs/data-contract.md)。不接入真实商家、支付账户或在线平台。

Python 3.11及以上，无第三方Python依赖。在项目根目录使用：

```sh
python -m unittest discover -s tests -v
python -m compileall -q source_data tests
python -m source_data.cli inspect data/normal.json
python -m source_data.cli collect data/normal.json
```

`inspect`仅读取清单、原始字节身份和基本配置，不覆盖资料。`collect`按MIME层级解析MHTML，输出主文档选择树、资源引用边、缺口与冲突清单：related容器按start或首子选根，alternative按preferred_types取一个表示，message/rfc822不透明留存；引用解析限定在所属related作用域，不执行页面脚本、不触网补齐。`invalid-config.json`是配置反例，其他清单有不同的源边界，边界报文可以保持合法清单但源内容不完整。资料中的姓名、编号、订单和站点均为虚构。

Dockerfile固定Linux基础镜像。`docker build -t commerce-source .`构建，`docker run --rm commerce-source`读取正常清单；`docker run --rm commerce-source python -m unittest discover -s tests -v`运行已有检查。运行资料均在本地，不需要账号、安装脚本或生产系统。
