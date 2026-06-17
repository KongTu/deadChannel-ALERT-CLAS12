#!/usr/bin/env run-groovy
//
// dump_alert_adc_csv.groovy
// -------------------------
// Dump the values shown on a deployed CLAS12 ALERT AHDC-ADC timeline into a
// tidy CSV (one row per run/layer/wire), so they can be analyzed in
// pandas / ROOT / a spreadsheet.
//
// The timeline values live in HIPO files as GraphErrors (one point per run),
// stored under the "/timelines/" directory inside each file. The graph names
// look like:  ahdc_adc_layer<L>_wire_number<WW>
//
// Based on clas12-timeline/util/dump-timelines.groovy. Like that tool, a
// clas12mon URL is rewritten to its local path on the JLab filesystem, so this
// is meant to be run ON IFARM (or pointed at HIPO files you have locally).
//
// Usage:
//   run-groovy dump_alert_adc_csv.groovy <input> <output.csv>
//     <input> may be:
//       - a clas12mon timeline URL (resolved to /group/clas/www/clas12mon/html/hipo/...)
//       - a directory containing timeline *.hipo files
//       - a single timeline *.hipo file
//
// Example (on ifarm):
//   run-groovy dump_alert_adc_csv.groovy \
//     https://clas12mon.jlab.org/rgl/pass0_v10.3_alert/alert/timeline/ alert_adc.csv
//
import org.jlab.groot.data.TDirectory
import java.util.regex.Pattern

def LAYER_CODE = [11, 21, 22, 31, 32, 41, 42, 51]   // layer_number 1..8 -> bank code

if (args.length < 2) {
  System.err.println("Usage: run-groovy dump_alert_adc_csv.groovy <url|dir|file> <output.csv>")
  System.exit(1)
}
def inSpec = args[0]
def outCsv = args[1]

// ---- resolve inputs to a list of HIPO files (same URL->path trick as the official tool)
def inFiles = []
if (inSpec ==~ /^https.*clas12mon.jlab.org.*timeline.*/) {
  def inDir = inSpec.replaceAll(/^.*jlab.org/, "/group/clas/www/clas12mon/html/hipo")
  inDir = "/" + inDir.tokenize('/')[0..-2].join("/")
  new File(inDir).traverse(type: groovy.io.FileType.FILES, nameFilter: ~/.*\.hipo/) {
    if (it.size() > 0) inFiles << inDir + "/" + it.getName()
  }
} else {
  def f = new File(inSpec)
  if (f.isDirectory()) {
    f.eachFileRecurse { if (it.name.endsWith('.hipo')) inFiles << it.absolutePath }
  } else {
    inFiles << inSpec
  }
}
inFiles = inFiles.sort()
if (inFiles.isEmpty()) { System.err.println("ERROR: no timeline .hipo files found for: $inSpec"); System.exit(1) }

println "Reading ${inFiles.size()} file(s)..."

// graph name -> (layer_number, wire); returns null if it isn't an AHDC-ADC wire graph
def nameRe = Pattern.compile(/ahdc_adc_layer(\d+)_wire_number(\d+)/)
def parseName = { String gname ->
  def m = nameRe.matcher(gname)
  return m.find() ? [m.group(1).toInteger(), m.group(2).toInteger()] : null
}

def writer = new PrintWriter(new File(outCsv))
writer.println("run,layer_number,layer_code,wire,value,graph_name")

int nRows = 0
inFiles.each { inFile ->
  def tdir = new TDirectory()
  try {
    tdir.readFile(inFile)
  } catch (Exception ex) {
    System.err.println("WARNING: cannot read $inFile (may be corrupt or empty), skipping")
    return
  }

  // collect the timeline GraphErrors (skip the helper plotLines and "__bad" graphs)
  tdir.getCompositeObjectList(tdir).each { objN ->
    def tok = objN.tokenize('/')
    if (tok[0] == "timelines" && !(tok[1] ==~ /^plotLine.*/) && !(tok[1] ==~ /.*__bad$/)) {
      def gr = tdir.getObject(objN)
      def gname = gr.getName()
      def lw = parseName(gname)
      if (lw == null) return   // skip anything that isn't an AHDC-ADC wire graph (ATOF, time, residual, ...)
      def layerNum = lw[0]
      def code     = LAYER_CODE[lw[0] - 1]
      def wire     = lw[1]
      int n = gr.getDataSize(0)
      n.times { i ->
        def run = (gr.getDataX(i)).toInteger()
        def val = gr.getDataY(i)
        writer.println("${run},${layerNum},${code},${wire},${val},${gname}")
        nRows++
      }
    }
  }
  println " - ${inFile.tokenize('/')[-1]}"
}
writer.close()
println "\nWrote ${nRows} rows -> ${outCsv}"
