<?xml version="1.0" encoding="UTF-8"?>
<!--
  XSLT Transform para heat.exe
  Remove apenas arquivos de cache Python do MSI.
  Mantemos .md, .txt, LICENSE etc. pois bibliotecas como mariadb, numpy
  e matplotlib referenciam esses arquivos em runtime (dist-info).

  Uses xsl:key to match Component IDs with ComponentRef IDs,
  ensuring both are removed together (hash-based IDs don't contain filenames).
-->
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:wix="http://schemas.microsoft.com/wix/2006/wi">

  <!-- Key to collect IDs of components that should be excluded -->
  <xsl:key name="ExcludedComponents" match="wix:Component[
    contains(wix:File/@Source, '__pycache__') or
    contains(wix:File/@Source, '.pyc') or
    contains(wix:File/@Source, '.pyo')
  ]" use="@Id"/>

  <!-- Identity transform: copy everything by default -->
  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>

  <!-- Remove components with Python cache files -->
  <xsl:template match="wix:Component[
    contains(wix:File/@Source, '__pycache__') or
    contains(wix:File/@Source, '.pyc') or
    contains(wix:File/@Source, '.pyo')
  ]"/>

  <!-- Remove ComponentRef whose Id matches a removed Component -->
  <xsl:template match="wix:ComponentRef[key('ExcludedComponents', @Id)]"/>

  <!-- Remove empty Directory elements (directories that had only excluded files) -->
  <xsl:template match="wix:Directory[not(*)]"/>

</xsl:stylesheet>