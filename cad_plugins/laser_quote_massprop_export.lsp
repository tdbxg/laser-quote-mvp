;;; Laser Quote MASSPROP exporter for AutoCAD-compatible CAD programs.
;;; Usage:
;;; 1. APPLOAD this file in CAD.
;;; 2. Run command LQEXPORT.
;;; 3. Select the same valid cutting objects you would use for MASSPROP.
;;; 4. Save the generated txt file and upload it as "MASSPROP text" in the web app.

(defun c:LQEXPORT (/ ss path oldcmdecho)
  (vl-load-com)
  (prompt "\nSelect valid cutting objects for MASSPROP export: ")
  (setq ss (ssget))
  (if (not ss)
    (prompt "\nNothing selected.")
    (progn
      (setq path (getfiled "Save MASSPROP TXT" "laser_quote_massprop.txt" "txt" 1))
      (if path
        (progn
          (setq oldcmdecho (getvar "CMDECHO"))
          (setvar "CMDECHO" 0)
          (vl-catch-all-apply
            '(lambda ()
               (vl-cmdf "_.MASSPROP" ss "" "_Y" path)
             )
          )
          (setvar "CMDECHO" oldcmdecho)
          (prompt (strcat "\nMASSPROP exported to: " path))
        )
        (prompt "\nExport cancelled.")
      )
    )
  )
  (princ)
)

(princ "\nCommand loaded: LQEXPORT")
(princ)
