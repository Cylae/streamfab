# Third-party notices

`src/static/js/vendor/lame.min.js` is the existing vendored lamejs/LAME browser MP3 encoder. It is loaded as a separate script and has not been modified by the audit.

- lamejs source: https://github.com/zhuker/lamejs
- Upstream license notice: https://github.com/zhuker/lamejs/blob/master/LICENSE
- LAME project and source: https://lame.sourceforge.io/
- LGPL license information: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html

The upstream project states that use is subject to the LGPL, requires acknowledgment of LAME, and requires release of modifications to LAME under the LGPL. Preserve applicable upstream notices and provide source/license access when redistributing the encoder.

The unused vendored MP4Box script was removed. Its presence previously implied browser remuxing that the application did not implement.

The repository does not contain a license grant for the application's own code. An MIT badge alone is not a license file; the audit removes the unsupported badge without assigning a new license on behalf of the owner.
