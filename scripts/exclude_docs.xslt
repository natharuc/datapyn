<?xml version="1.0" encoding="UTF-8"?>
<!--
  XSLT Transform para heat.exe
  Remove arquivos desnecessarios do MSI (docs, logs, cache, etc.)
-->
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:wix="http://schemas.microsoft.com/wix/2006/wi">

  <!-- Identity transform: copy everything by default -->
  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>

  <!-- Remove components with files matching documentation patterns -->
  <xsl:template match="wix:Component[
    contains(wix:File/@Source, '.md') or
    contains(wix:File/@Source, '.txt') or
    contains(wix:File/@Source, '.rst') or
    contains(wix:File/@Source, '.log') or
    contains(wix:File/@Source, 'README') or
    contains(wix:File/@Source, 'LICENSE') or
    contains(wix:File/@Source, 'CHANGELOG') or
    contains(wix:File/@Source, 'INTEGRATION_GUIDE') or
    contains(wix:File/@Source, '__pycache__') or
    contains(wix:File/@Source, '.pyc') or
    contains(wix:File/@Source, '.pyo')
  ]"/>

  <!-- Remove ComponentRef for excluded components -->
  <xsl:template match="wix:ComponentRef[
    contains(@Id, '.md') or
    contains(@Id, '.txt') or
    contains(@Id, '.rst') or
    contains(@Id, '.log') or
    contains(@Id, 'README') or
    contains(@Id, 'LICENSE') or
    contains(@Id, 'CHANGELOG') or
    contains(@Id, 'INTEGRATION_GUIDE') or
    contains(@Id, '__pycache__') or
    contains(@Id, '.pyc') or
    contains(@Id, '.pyo')
  ]"/>

</xsl:stylesheet>
