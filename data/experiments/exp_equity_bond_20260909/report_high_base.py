"""Apply the same reporting and checks to low-only deleveraging."""
import report
if __name__=='__main__':
    report.EXP=report.EXP/'high_base'
    report.main()
