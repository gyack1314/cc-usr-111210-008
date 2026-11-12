# 网页留存作用域

related根只能由直接子部件选择，根本身若为alternative则按preferred_types递归选择一个叶表示；嵌套related创建新资源表，不把子资源提升为父资源。message/rfc822不递归。Content-ID去外部尖括号后保持大小写，cid URL仅百分号解码一次，不把+当空格。

每容器基址先继承父基址，再以容器Content-Base覆盖（相对值先解析），根Content-Location在此基上解析为根地址；根叶Content-Base可覆盖文档基，最后HTML第一个可解析的base href更新文档引用基。叶Content-Location相对其所属容器基址解析；CSS中的相对url基于该CSS的Content-Location。URL规范只做RFC3986相对解析和点段去除、scheme/host小写，不改query，不删除fragment原文；资源查找用去fragment地址。

HTML通过解析器读属性。srcset支持常规URL配w/x描述符与data URL，CSS小语法支持注释、单双引号、反斜杠转义及url()；不展开@import或动态脚本，超出语法列unparsed。data URI留内嵌引用，不加入外部缺口。原MIME范围与解码叶摘要分别记录，编码后边界正文不按子串切。
