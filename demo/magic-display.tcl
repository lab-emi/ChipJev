# Read-only native Magic viewer, launched on the worker's private X server.
# Only an integer revision is accepted; no browser text is evaluated as Tcl.
crashbackups stop
drc off
wm geometry .layout1 $chipjev_geometry
wm title .layout1 {ChipJev | LIVE Magic | SKY130}
load waiting-for-layout
grid off
set chipjev_layout 0
set fd [open magic-shown.txt w]
puts $fd 0
close $fd

proc chipjev_layout_tick {} {
    global chipjev_layout
    drc off
    if {[file exists magic-stage.txt]} {
        set fd [open magic-stage.txt r]
        set next [string trim [read $fd 16]]
        close $fd
        if {[regexp {^[0-9]{1,4}$} $next] && $next != $chipjev_layout} {
            if {[catch {
                set win [lindex [windownames layout] 0]
                $win load [file normalize view-$next.mag]
                $win see "*"
                $win select top cell
                $win expand
                $win select clear
                $win view
                $win redraw
                update
            } problem]} {
                puts stderr $::errorInfo
                exit 1
            }
            set chipjev_layout $next
            set fd [open magic-shown.txt.tmp w]
            puts $fd $next
            close $fd
            file rename -force magic-shown.txt.tmp magic-shown.txt
        }
    }
    after 40 chipjev_layout_tick
}
after 100 chipjev_layout_tick
